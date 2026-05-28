"""图片下载与正文图片本地化服务。

负责封面、章节插图的安全 URL 解析、格式识别、去重下载和 HTML 引用替换。"""

from __future__ import annotations

import hashlib
import mimetypes
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from PIL import Image, UnidentifiedImageError

from .client import ALLOWED_ESJ_HOSTS, EsjHttpClient
from .models import BookMetadata


class ImageService:
    """处理封面和章节插图下载、格式识别与正文引用替换。"""
    def __init__(self, client_factory: EsjHttpClient, config: Any = None, logger: Any = None):
        """初始化对象依赖和运行时目录。"""
        self.client_factory = client_factory
        self.config = config or {}
        self.logger = logger

    def _allow_external_images(self) -> bool:
        """读取是否允许下载站外图片的配置。"""
        download_cfg = self.config.get("download", {}) if hasattr(self.config, "get") else {}
        return bool(download_cfg.get("allow_external_images", True))

    @staticmethod
    def _ext_from_content_type(content_type: str, fallback_url: str = "") -> str:
        """根据响应 Content-Type 或 URL 推断图片扩展名。"""
        mapping = {
            "image/jpeg": ".jpg",
            "image/jpg": ".jpg",
            "image/png": ".png",
            "image/gif": ".gif",
            "image/webp": ".webp",
            "image/svg+xml": ".svg",
            "image/avif": ".avif",
        }
        if content_type in mapping:
            return mapping[content_type]
        suffix = Path(urlparse(fallback_url).path).suffix.lower()
        if suffix in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".avif"}:
            return ".jpg" if suffix == ".jpeg" else suffix
        guessed = mimetypes.guess_extension(content_type or "")
        return ".jpg" if guessed == ".jpe" else (guessed or ".bin")

    @staticmethod
    def _detect_ext_from_magic(data: bytes) -> tuple[str, str] | None:
        """根据文件魔数识别常见图片格式。"""
        head = data[:32]
        stripped = data[:256].lstrip()

        if head.startswith(b"\xff\xd8\xff"):
            return ".jpg", "image/jpeg"
        if head.startswith(b"\x89PNG\r\n\x1a\n"):
            return ".png", "image/png"
        if head.startswith((b"GIF87a", b"GIF89a")):
            return ".gif", "image/gif"
        if len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WEBP":
            return ".webp", "image/webp"
        if b"ftypavif" in head or b"ftypavis" in head:
            return ".avif", "image/avif"
        if stripped.startswith(b"<svg") or b"<svg" in stripped[:128]:
            return ".svg", "image/svg+xml"
        return None

    @staticmethod
    def _normalize_image_data(data: bytes, content_type: str, fallback_url: str = "") -> tuple[bytes, str, str]:
        """
        规范化图片数据、扩展名和 media type。

        很多图床会返回 application/octet-stream 或空 Content-Type，导致旧逻辑保存为 .bin。
        这里优先按文件头判断真实格式；如果仍无法判断，再尝试用 Pillow 识别。
        Pillow 能识别但 EPUB 兼容性不稳的未知格式会转成 PNG。
        """
        magic = ImageService._detect_ext_from_magic(data)
        if magic:
            ext, media_type = magic
            return data, ext, media_type

        ext = ImageService._ext_from_content_type(content_type, fallback_url)
        if ext != ".bin":
            media_type = ImageService._media_type_from_ext(ext, content_type)
            return data, ext, media_type

        try:
            with Image.open(BytesIO(data)) as image:
                fmt = (image.format or "").upper()
                format_map = {
                    "JPEG": (".jpg", "image/jpeg"),
                    "JPG": (".jpg", "image/jpeg"),
                    "PNG": (".png", "image/png"),
                    "GIF": (".gif", "image/gif"),
                    "WEBP": (".webp", "image/webp"),
                    "AVIF": (".avif", "image/avif"),
                }
                if fmt in format_map:
                    detected_ext, detected_media = format_map[fmt]
                    return data, detected_ext, detected_media

                # Pillow 识别到了图片，但格式不适合直接嵌入 EPUB，则转 PNG。
                output = BytesIO()
                converted = image.convert("RGBA") if image.mode in {"P", "LA", "RGBA"} else image.convert("RGB")
                converted.save(output, format="PNG")
                return output.getvalue(), ".png", "image/png"
        except (UnidentifiedImageError, OSError, ValueError):
            return data, ".bin", "application/octet-stream"

    @staticmethod
    def _media_type_from_ext(ext: str, content_type: str = "") -> str:
        """根据图片扩展名推断媒体类型。"""
        mapping = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".svg": "image/svg+xml",
            ".avif": "image/avif",
        }
        if ext in mapping:
            return mapping[ext]
        if content_type:
            return content_type
        return "application/octet-stream"

    @staticmethod
    def _media_type_from_path(path: Path, content_type: str = "") -> str:
        """根据文件扩展名推断资源媒体类型。"""
        if content_type and content_type != "application/octet-stream":
            return content_type
        guessed, _ = mimetypes.guess_type(path.name)
        return guessed or "application/octet-stream"

    @staticmethod
    def _safe_image_url(raw_url: str, base_url: str, allow_external: bool = False) -> str:
        """将正文图片地址解析为安全可下载的绝对 URL。"""
        value = (raw_url or "").strip()
        if not value:
            return ""
        if value.startswith("data:"):
            return ""

        absolute = urljoin(base_url, value)
        parsed = urlparse(absolute)
        if parsed.scheme not in {"https", "http"}:
            return ""
        if parsed.username or parsed.password:
            return ""
        if not parsed.hostname:
            return ""
        if not allow_external and parsed.hostname not in ALLOWED_ESJ_HOSTS:
            return ""
        return absolute

    @staticmethod
    def _image_filename(url: str, index: int, ext: str) -> str:
        """按序号和 URL 哈希生成稳定的本地图片文件名。"""
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
        return f"{index:05d}_{digest}{ext}"

    async def download_cover(self, client: httpx.AsyncClient, metadata: BookMetadata, book_dir: Path) -> tuple[Path | None, int]:
        """下载封面图并更新书籍元数据中的本地路径。"""
        if not metadata.cover_url:
            return None, 0

        try:
            cover_url = self._safe_image_url(
                metadata.cover_url,
                metadata.detail_url,
                allow_external=self._allow_external_images(),
            )
            if not cover_url:
                raise ValueError("封面 URL 不在允许范围内")

            data, content_type = await self.client_factory.get_bytes(
                client,
                cover_url,
                referer=metadata.detail_url,
                allow_external=self._allow_external_images(),
            )
            data, ext, _media_type = self._normalize_image_data(data, content_type, cover_url)
            if ext == ".bin":
                raise ValueError("封面不是可识别图片格式")
            cover_path = book_dir / f"cover{ext}"
            cover_path.write_bytes(data)
            return cover_path, 0
        except Exception as exc:
            if self.logger:
                self.logger.warning(f"封面下载失败: {metadata.cover_url} / {type(exc).__name__}: {exc}")
            return None, 1

    async def process_chapter_images(
        self,
        client: httpx.AsyncClient,
        metadata: BookMetadata,
        chapters: list[dict],
        book_dir: Path,
    ) -> tuple[list[dict], list[dict], int]:
        """下载章节内图片并把 HTML 引用替换为本地相对路径。"""
        illustrations_dir = book_dir / "illustrations"
        illustrations_dir.mkdir(parents=True, exist_ok=True)

        image_map: dict[str, dict] = {}
        image_items: list[dict] = []
        failed_images = 0
        allow_external = self._allow_external_images()

        async def ensure_image(url: str, referer: str) -> dict | None:
            """下载并缓存单张章节图片，重复 URL 直接复用。"""
            nonlocal failed_images
            if url in image_map:
                return image_map[url]

            try:
                data, content_type = await self.client_factory.get_bytes(
                    client,
                    url,
                    referer=referer,
                    allow_external=allow_external,
                )
                data, ext, media_type = self._normalize_image_data(data, content_type, url)
                if ext == ".bin":
                    raise ValueError("不是可识别图片格式")

                filename = self._image_filename(url, len(image_items) + 1, ext)
                file_path = illustrations_dir / filename
                file_path.write_bytes(data)
                item = {
                    "url": url,
                    "path": str(file_path),
                    "epub_href": f"images/{filename}",
                    "media_type": media_type,
                    "size": len(data),
                }
                image_map[url] = item
                image_items.append(item)
                return item
            except Exception as exc:
                failed_images += 1
                if self.logger:
                    self.logger.warning(f"插图下载失败: {url} / {type(exc).__name__}: {exc}")
                return None

        processed: list[dict] = []
        for chapter in chapters:
            html = chapter.get("html") or ""
            if not html:
                processed.append(chapter)
                continue

            soup = BeautifulSoup(html, "lxml")
            changed = False
            for img in soup.select("img"):
                raw_url = (
                    img.get("src")
                    or img.get("data-src")
                    or img.get("data-original")
                    or img.get("data-lazy-src")
                    or ""
                )
                image_url = self._safe_image_url(
                    raw_url,
                    chapter.get("url") or metadata.detail_url,
                    allow_external=allow_external,
                )
                if not image_url:
                    continue

                item = await ensure_image(image_url, chapter.get("url") or metadata.detail_url)
                if not item:
                    continue

                img["src"] = item["epub_href"]
                for attr in ("data-src", "data-original", "data-lazy-src", "srcset"):
                    if img.has_attr(attr):
                        del img[attr]
                changed = True

            if changed:
                next_chapter = dict(chapter)
                body = soup.body
                next_chapter["processed_html"] = body.decode_contents() if body else str(soup)
                processed.append(next_chapter)
            else:
                processed.append(chapter)

        return processed, image_items, failed_images
