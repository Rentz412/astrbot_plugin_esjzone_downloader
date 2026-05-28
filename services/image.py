from __future__ import annotations

import hashlib
import mimetypes
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from .client import ALLOWED_ESJ_HOSTS, EsjHttpClient
from .models import BookMetadata


class ImageService:
    def __init__(self, client_factory: EsjHttpClient, config: Any = None, logger: Any = None):
        self.client_factory = client_factory
        self.config = config or {}
        self.logger = logger

    def _allow_external_images(self) -> bool:
        download_cfg = self.config.get("download", {}) if hasattr(self.config, "get") else {}
        return bool(download_cfg.get("allow_external_images", True))

    @staticmethod
    def _ext_from_content_type(content_type: str, fallback_url: str = "") -> str:
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
    def _media_type_from_path(path: Path, content_type: str = "") -> str:
        if content_type:
            return content_type
        guessed, _ = mimetypes.guess_type(path.name)
        return guessed or "application/octet-stream"

    @staticmethod
    def _safe_image_url(raw_url: str, base_url: str, allow_external: bool = False) -> str:
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
    def _image_filename(url: str, index: int, content_type: str = "") -> str:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
        ext = ImageService._ext_from_content_type(content_type, url)
        return f"{index:05d}_{digest}{ext}"

    async def download_cover(self, client: httpx.AsyncClient, metadata: BookMetadata, book_dir: Path) -> tuple[Path | None, int]:
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
            ext = self._ext_from_content_type(content_type, cover_url)
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
        illustrations_dir = book_dir / "illustrations"
        illustrations_dir.mkdir(parents=True, exist_ok=True)

        image_map: dict[str, dict] = {}
        image_items: list[dict] = []
        failed_images = 0
        allow_external = self._allow_external_images()

        async def ensure_image(url: str, referer: str) -> dict | None:
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
                filename = self._image_filename(url, len(image_items) + 1, content_type)
                file_path = illustrations_dir / filename
                file_path.write_bytes(data)
                item = {
                    "url": url,
                    "path": str(file_path),
                    "epub_href": f"images/{filename}",
                    "media_type": self._media_type_from_path(file_path, content_type),
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
