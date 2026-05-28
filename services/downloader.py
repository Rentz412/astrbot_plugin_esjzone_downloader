from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any, Mapping

from .client import EsjHttpClient
from .exporter_epub import EpubExporter
from .exporter_txt import TxtExporter
from .image import ImageService
from .models import AuthContext, DownloadResult
from .packer import ZipPacker
from .parser import normalize_esj_input, parse_book_detail, parse_chapter_content
from .repository import EsjRepository


class EsjDownloader:
    def __init__(self, data_dir: Path, config: Mapping, logger: Any = None):
        self.data_dir = data_dir
        self.config = config
        self.logger = logger
        self.client_factory = EsjHttpClient(config)
        self.repo = EsjRepository(data_dir)
        self.txt_exporter = TxtExporter()
        self.epub_exporter = EpubExporter()
        self.image_service = ImageService(self.client_factory, config, logger)
        self.packer = ZipPacker(config)

    def _debug_cfg(self) -> dict[str, Any]:
        cfg = self.config.get("debug", {}) if hasattr(self.config, "get") else {}
        return cfg if isinstance(cfg, dict) else {}

    def _debug_enabled(self) -> bool:
        return bool(self._debug_cfg().get("enabled", False))

    def _debug_dir(self) -> Path:
        path = self.data_dir / "debug" / "pages"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _debug_log(self, message: str) -> None:
        if self._debug_enabled() and self.logger:
            self.logger.info(f"[esj.debug][downloader] {message}")

    def _debug_write_text(self, filename: str, text: str, chapter_page: bool = False) -> None:
        cfg = self._debug_cfg()
        if not cfg.get("enabled", False):
            return
        if chapter_page and not cfg.get("save_chapter_pages", False):
            return
        if not chapter_page and not cfg.get("save_pages", True):
            return
        (self._debug_dir() / filename).write_text(text, encoding="utf-8", errors="replace")

    def _debug_write_json(self, filename: str, payload: dict[str, Any]) -> None:
        cfg = self._debug_cfg()
        if not cfg.get("enabled", False):
            return
        (self._debug_dir() / filename).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _safe_name(value: str) -> str:
        cleaned = re.sub(r"[^0-9A-Za-z_.-]+", "_", value or "")
        return cleaned.strip("._") or "unknown"

    @staticmethod
    def _html_title(html: str) -> str:
        match = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
        if not match:
            return ""
        return re.sub(r"\s+", " ", match.group(1)).strip()

    @staticmethod
    def _looks_like_login_or_home(html: str) -> bool:
        markers = (
            "注册",
            "註冊",
            "登录",
            "登入",
            "/my/login",
            "/login",
            "window.location.href='/my/login';",
            'window.location.href="/my/login";',
        )
        return any(marker in html for marker in markers)

    def _range_slice(self, total: int, start: int = 0, end: int = 0) -> slice:
        if total <= 0:
            return slice(0, 0)
        start_idx = max((start or 1) - 1, 0)
        end_idx = total if not end else min(end, total)
        if end_idx < start_idx + 1:
            raise ValueError("结束章节不能小于起始章节")
        return slice(start_idx, end_idx)

    async def fetch_info(self, auth: AuthContext, raw: str):
        normalized = normalize_esj_input(raw)
        safe_book_id = self._safe_name(normalized.book_id)
        self._debug_log(
            f"fetch_info raw={raw} book_id={normalized.book_id} detail_url={normalized.detail_url} "
            f"auth_cookie_len={len(auth.cookie or '')} auth_cookie_jar={len(auth.cookie_jar or [])}"
        )

        async with self.client_factory.build_client(auth) as client:
            html = await self.client_factory.get_text(client, normalized.detail_url)

        response_info = dict(self.client_factory.last_response_info)
        self._debug_write_text(f"detail_{safe_book_id}.html", html)
        metadata, chapters = parse_book_detail(html, normalized)
        self._debug_write_json(
            f"detail_{safe_book_id}.json",
            {
                "raw": raw,
                "book_id": normalized.book_id,
                "detail_url": normalized.detail_url,
                "response": response_info,
                "title_tag": self._html_title(html),
                "html_length": len(html),
                "contains_book_detail": "book-detail" in html,
                "contains_chapter_list": "chapterList" in html,
                "contains_login_or_home_markers": self._looks_like_login_or_home(html),
                "parsed_title": metadata.title,
                "parsed_author": metadata.author,
                "parsed_intro_length": len(metadata.intro_text or ""),
                "chapter_count": len(chapters),
                "chapters_preview": [
                    {"index": chapter.index, "chapter_id": chapter.chapter_id, "title": chapter.title, "url": chapter.url}
                    for chapter in chapters[:30]
                ],
            },
        )
        self._debug_log(
            f"fetch_info parsed title={metadata.title!r} chapters={len(chapters)} "
            f"final_url={response_info.get('final_url')} len={len(html)}"
        )
        return metadata, chapters

    async def download(self, auth: AuthContext, raw: str, fmt: str = "epub", start: int = 0, end: int = 0) -> DownloadResult:
        fmt = (fmt or self.config.get("download", {}).get("default_format", "epub")).lower()
        if fmt not in {"epub", "txt"}:
            raise ValueError("当前版本仅支持 epub 和 txt。")

        metadata, chapters = await self.fetch_info(auth, raw)
        if not chapters:
            self._debug_log(f"download aborted empty chapters book_id={metadata.book_id} title={metadata.title!r}")
            raise ValueError(f"章节列表为空，无法下载。调试目录：{self._debug_dir()}")

        chapters_to_download = chapters[self._range_slice(len(chapters), start, end)]
        self._debug_log(
            f"download start book_id={metadata.book_id} fmt={fmt} total={len(chapters)} "
            f"selected={len(chapters_to_download)} start={start or 1} end={end or len(chapters)}"
        )
        book_dir = self.repo.book_dir(metadata.book_id)
        remote_fp = self.repo.fingerprint(chapters)
        status = self.repo.load_status(metadata.book_id)
        output_ext = ".epub" if fmt == "epub" else ".txt"
        output_file = book_dir / "outputs" / f"{metadata.safe_title}{output_ext}"

        if status and status.get("chapter_fingerprint") == remote_fp and output_file.exists():
            package_path, password = self.packer.pack(book_dir, output_file, metadata.book_id, metadata.safe_title)
            return DownloadResult(metadata.book_id, metadata.title, str(output_file), str(package_path), password, True, fmt, len(chapters_to_download))

        if status and status.get("chapter_fingerprint") != remote_fp:
            self.repo.clear_book_runtime(metadata.book_id)

        self.repo.save_metadata(metadata)
        failed = 0
        concurrency = max(1, min(int(self.config.get("download", {}).get("concurrency", 5)), 10))
        semaphore = asyncio.Semaphore(concurrency)

        async with self.client_factory.build_client(auth) as client:
            async def fetch_one(chapter):
                nonlocal failed
                async with semaphore:
                    try:
                        html = await self.client_factory.get_text(client, chapter.url, referer=metadata.detail_url)
                        self._debug_write_text(
                            f"chapter_{metadata.book_id}_{chapter.index + 1:05d}_{chapter.chapter_id}.html",
                            html,
                            chapter_page=True,
                        )
                        content = parse_chapter_content(html, chapter)
                        self.repo.save_chapter(metadata.book_id, content)
                    except Exception as exc:
                        failed += 1
                        self._debug_write_json(
                            f"chapter_{metadata.book_id}_{chapter.index + 1:05d}_{chapter.chapter_id}.error.json",
                            {
                                "book_id": metadata.book_id,
                                "index": chapter.index,
                                "chapter_id": chapter.chapter_id,
                                "title": chapter.title,
                                "url": chapter.url,
                                "error_type": type(exc).__name__,
                                "error": str(exc),
                                "response": dict(self.client_factory.last_response_info),
                            },
                        )
                        if self.logger:
                            self.logger.exception(f"章节下载失败: {chapter.title}")

            await asyncio.gather(*(fetch_one(c) for c in chapters_to_download))

        cached = self.repo.load_chapters(metadata.book_id)
        if not cached:
            raise ValueError("没有可导出的章节内容。")

        cover_path = None
        image_items: list[dict] = []
        failed_images = 0
        if fmt == "epub" and self.config.get("download", {}).get("enable_image_download", True):
            async with self.client_factory.build_client(auth) as client:
                cover_path, cover_failed = await self.image_service.download_cover(client, metadata, book_dir)
                cached, image_items, chapter_image_failed = await self.image_service.process_chapter_images(
                    client,
                    metadata,
                    cached,
                    book_dir,
                )
                failed_images = cover_failed + chapter_image_failed
            self._debug_log(
                f"images processed book_id={metadata.book_id} cover={bool(cover_path)} "
                f"illustrations={len(image_items)} failed_images={failed_images}"
            )
            self._debug_write_json(
                f"images_{metadata.book_id}.json",
                {
                    "book_id": metadata.book_id,
                    "cover_path": str(cover_path) if cover_path else "",
                    "illustration_count": len(image_items),
                    "failed_images": failed_images,
                    "images_preview": image_items[:30],
                },
            )

        if fmt == "txt":
            output_file = self.txt_exporter.export(book_dir, metadata, cached)
        else:
            output_file = self.epub_exporter.export(
                book_dir,
                metadata,
                cached,
                cover_path=cover_path,
                image_items=image_items,
            )

        package_path, password = self.packer.pack(book_dir, output_file, metadata.book_id, metadata.safe_title)
        self.repo.save_status(
            metadata,
            chapters,
            fmt,
            package_path,
            failed_chapters=failed,
            failed_images=failed_images,
            has_cover=bool(cover_path),
            illustration_count=len(image_items),
        )
        self._debug_write_json(
            f"download_{metadata.book_id}.json",
            {
                "book_id": metadata.book_id,
                "title": metadata.title,
                "format": fmt,
                "total_chapters": len(chapters),
                "selected_chapters": len(chapters_to_download),
                "exported_chapters": len(cached),
                "failed_chapters": failed,
                "failed_images": failed_images,
                "has_cover": bool(cover_path),
                "illustration_count": len(image_items),
                "output_file": str(output_file),
                "package_path": str(package_path),
            },
        )
        self._debug_log(
            f"download finished book_id={metadata.book_id} exported={len(cached)} failed={failed} package={package_path}"
        )
        return DownloadResult(metadata.book_id, metadata.title, str(output_file), str(package_path), password, False, fmt, len(cached))
