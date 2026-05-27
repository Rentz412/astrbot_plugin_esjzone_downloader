from __future__ import annotations

import asyncio
from pathlib import Path

from .client import EsjHttpClient
from .exporter_epub import EpubExporter
from .exporter_txt import TxtExporter
from .image import ImageService
from .models import AuthContext, ChapterData, DownloadOptions, DownloadResult, EsjUrlType
from .packer import ZipPacker
from .parser import EsjParser
from .repository import BookRepository


class DownloadService:
    def __init__(
        self,
        client: EsjHttpClient,
        parser: EsjParser,
        repository: BookRepository,
        image_service: ImageService,
        txt_exporter: TxtExporter,
        epub_exporter: EpubExporter,
        packer: ZipPacker,
        config_getter,
    ) -> None:
        self.client = client
        self.parser = parser
        self.repository = repository
        self.image_service = image_service
        self.txt_exporter = txt_exporter
        self.epub_exporter = epub_exporter
        self.packer = packer
        self.config_getter = config_getter

    async def get_info(self, raw: str, auth: AuthContext) -> tuple[object, list[object]]:
        book_id, url, url_type = self.parser.normalize_input(raw)
        detail_url = self.parser.build_detail_url(book_id) if url_type != EsjUrlType.DETAIL else url
        html = await self.client.fetch_text(detail_url, auth=auth)
        metadata = self.parser.parse_book_metadata(html, book_id, detail_url)
        chapters = self.parser.parse_chapter_list(html, detail_url)
        if not chapters and metadata.forum_url:
            forum_html = await self.client.fetch_text(metadata.forum_url, auth=auth)
            chapters = self.parser.parse_chapter_list(forum_html, metadata.forum_url)
        return metadata, chapters

    async def download(
        self,
        raw: str,
        auth: AuthContext,
        options: DownloadOptions,
        progress_cb=None,
    ) -> DownloadResult:
        metadata, chapters = await self.get_info(raw, auth)
        if not chapters:
            raise RuntimeError("未解析到章节列表")

        fmt = options.fmt
        if fmt not in {"epub", "txt"}:
            raise ValueError("当前版本仅支持 epub 和 txt")

        start = max(1, options.start or 1)
        end = options.end or len(chapters)
        end = min(end, len(chapters))
        selected = chapters[start - 1 : end]
        if not selected:
            raise ValueError("章节范围无效")

        self.repository.ensure_book_dirs(metadata.book_id)
        need_download, reason = self.repository.needs_download(metadata.book_id, chapters, fmt)

        if reason == "changed" or options.force:
            self.repository.clear_book_content_for_redownload(metadata.book_id)

        output_path = self.repository.output_path(metadata, fmt)
        if reason == "reuse" and output_path.exists() and not options.force:
            package_path, password = self._pack(metadata, [output_path])
            return DownloadResult(
                book_id=metadata.book_id,
                title=metadata.title,
                output_path=output_path,
                package_path=package_path,
                zip_password=password,
                reused=True,
                format=fmt,
            )

        if need_download or reason in {"missing", "changed"} or options.force:
            await self._download_chapters(metadata.book_id, selected, auth, progress_cb)
            self.repository.write_metadata(metadata)
            cover_path = await self.image_service.download_cover(
                metadata.cover_url,
                self.repository.book_dir(metadata.book_id) / "cover.jpg",
                auth,
                metadata.detail_url,
            )
        else:
            cover_path = self._find_cover(self.repository.book_dir(metadata.book_id))

        chapter_data = self.repository.load_all_chapters(metadata.book_id, len(chapters))
        if len(chapter_data) < len(selected):
            chapter_data = [item for item in chapter_data if start - 1 <= item.index <= end - 1]
        else:
            chapter_data = [item for item in chapter_data if start - 1 <= item.index <= end - 1]

        if fmt == "txt":
            await self.txt_exporter.export(metadata, chapter_data, output_path)
        else:
            await self.epub_exporter.export(metadata, chapter_data, output_path, cover_path=cover_path)

        status = self.repository.load_status(metadata.book_id) or {}
        formats = list(status.get("downloaded_formats", []))
        if fmt not in formats:
            formats.append(fmt)

        package_path, password = self._pack(metadata, [output_path])
        self.repository.write_status(
            metadata,
            chapters,
            formats,
            package_path,
            failed_chapters=sum(1 for item in chapter_data if item.error),
            failed_images=sum(item.image_errors for item in chapter_data),
        )

        return DownloadResult(
            book_id=metadata.book_id,
            title=metadata.title,
            output_path=output_path,
            package_path=package_path,
            zip_password=password,
            reused=False,
            format=fmt,
        )

    async def _download_chapters(self, book_id: str, chapters: list[object], auth: AuthContext, progress_cb=None) -> None:
        download_cfg = self.config_getter("download", {})
        concurrency = int(download_cfg.get("concurrency", 5) or 5)
        concurrency = max(1, min(concurrency, 10))
        semaphore = asyncio.Semaphore(concurrency)
        completed = 0

        async def worker(task) -> None:
            nonlocal completed
            async with semaphore:
                try:
                    if getattr(task, "is_external", False):
                        chapter = self.parser.parse_chapter_html("", task)
                    else:
                        html = await self.client.fetch_text(task.url, auth=auth)
                        chapter = self.parser.parse_chapter_html(html, task)
                except Exception as exc:
                    chapter = ChapterData(
                        index=task.index,
                        title=task.title,
                        author="",
                        content_html="",
                        content_text="",
                        txt_segment=f"{task.title}\n\n下载失败：{type(exc).__name__}\n",
                        error=str(exc),
                    )
                self.repository.save_chapter(book_id, chapter)
                completed += 1
                if progress_cb:
                    await progress_cb(completed, len(chapters), task.title)

        await asyncio.gather(*(worker(task) for task in chapters))

    def _pack(self, metadata, files: list[Path]) -> tuple[Path, str]:
        zip_cfg = self.config_getter("zip", {})
        password = self.packer.make_password(
            metadata.book_id,
            mode=zip_cfg.get("password_mode", "book_id"),
            fixed_password=zip_cfg.get("fixed_password", "esjzone"),
            random_length=int(zip_cfg.get("random_password_length", 8) or 8),
        )
        package_path = self.repository.package_path(metadata)
        self.packer.pack(files, package_path, password)
        return package_path, password

    def _find_cover(self, book_dir: Path) -> Path | None:
        for name in ("cover.jpg", "cover.png", "cover.webp", "cover.gif"):
            path = book_dir / name
            if path.exists():
                return path
        return None
