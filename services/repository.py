from __future__ import annotations

import json
import shutil
import time
from hashlib import sha256
from pathlib import Path
from typing import Any

from .models import BookMetadata, ChapterData, ChapterTask
from .utils import ensure_within_base


class BookRepository:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.books_dir = data_dir / "books"
        self.books_dir.mkdir(parents=True, exist_ok=True)

    def book_dir(self, book_id: str) -> Path:
        return ensure_within_base(self.data_dir, self.books_dir / book_id)

    def chapters_dir(self, book_id: str) -> Path:
        return self.book_dir(book_id) / "chapters"

    def outputs_dir(self, book_id: str) -> Path:
        return self.book_dir(book_id) / "outputs"

    def packages_dir(self, book_id: str) -> Path:
        return self.book_dir(book_id) / "packages"

    def illustrations_dir(self, book_id: str) -> Path:
        return self.book_dir(book_id) / "illustrations"

    def logs_dir(self, book_id: str) -> Path:
        return self.book_dir(book_id) / "logs"

    def ensure_book_dirs(self, book_id: str) -> None:
        for path in (
            self.book_dir(book_id),
            self.chapters_dir(book_id),
            self.outputs_dir(book_id),
            self.packages_dir(book_id),
            self.illustrations_dir(book_id),
            self.logs_dir(book_id),
        ):
            path.mkdir(parents=True, exist_ok=True)

    def status_path(self, book_id: str) -> Path:
        return self.book_dir(book_id) / "status.json"

    def metadata_path(self, book_id: str) -> Path:
        return self.book_dir(book_id) / "metadata.json"

    def chapter_path(self, book_id: str, index: int) -> Path:
        return self.chapters_dir(book_id) / f"{index + 1:05d}.json"

    def load_status(self, book_id: str) -> dict[str, Any] | None:
        path = self.status_path(book_id)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def write_status(
        self,
        metadata: BookMetadata,
        chapters: list[ChapterTask],
        downloaded_formats: list[str],
        package_path: Path | None,
        failed_chapters: int = 0,
        failed_images: int = 0,
    ) -> None:
        self.ensure_book_dirs(metadata.book_id)
        fingerprint = self.chapter_fingerprint(chapters)
        latest = chapters[-1] if chapters else None
        payload = {
            "version": 1,
            "book_id": metadata.book_id,
            "title": metadata.title,
            "author": metadata.author,
            "source_url": metadata.detail_url,
            "detail_url": metadata.detail_url,
            "forum_url": metadata.forum_url,
            "chapter_count": len(chapters),
            "latest_chapter_title": latest.title if latest else "",
            "latest_chapter_url": latest.url if latest else "",
            "chapter_fingerprint": fingerprint,
            "last_remote_check_at": int(time.time()),
            "last_download_at": int(time.time()),
            "downloaded_formats": sorted(set(downloaded_formats)),
            "package_path": str(package_path.relative_to(self.book_dir(metadata.book_id))) if package_path else "",
            "has_cover": (self.book_dir(metadata.book_id) / "cover.jpg").exists(),
            "illustration_count": len(list(self.illustrations_dir(metadata.book_id).glob("*"))),
            "failed_chapters": failed_chapters,
            "failed_images": failed_images,
        }
        self.status_path(metadata.book_id).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def write_metadata(self, metadata: BookMetadata) -> None:
        self.ensure_book_dirs(metadata.book_id)
        payload = {
            "book_id": metadata.book_id,
            "title": metadata.title,
            "safe_title": metadata.safe_title,
            "author": metadata.author,
            "description": metadata.intro_text,
            "info_block": metadata.info_block,
            "cover_path": "cover.jpg",
            "source_url": metadata.detail_url,
            "created_at": int(time.time()),
            "updated_at": int(time.time()),
        }
        self.metadata_path(metadata.book_id).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def save_chapter(self, book_id: str, chapter: ChapterData) -> None:
        self.ensure_book_dirs(book_id)
        payload = {
            "index": chapter.index,
            "title": chapter.title,
            "author": chapter.author,
            "content_html": chapter.content_html,
            "content_text": chapter.content_text,
            "txt_segment": chapter.txt_segment,
            "image_errors": chapter.image_errors,
            "error": chapter.error,
        }
        self.chapter_path(book_id, chapter.index).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def load_chapter(self, book_id: str, index: int) -> ChapterData | None:
        path = self.chapter_path(book_id, index)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return ChapterData(
            index=data["index"],
            title=data["title"],
            author=data.get("author", ""),
            content_html=data.get("content_html", ""),
            content_text=data.get("content_text", ""),
            txt_segment=data.get("txt_segment", ""),
            image_errors=data.get("image_errors", 0),
            error=data.get("error"),
        )

    def load_all_chapters(self, book_id: str, total: int) -> list[ChapterData]:
        chapters: list[ChapterData] = []
        for index in range(total):
            chapter = self.load_chapter(book_id, index)
            if chapter:
                chapters.append(chapter)
        return chapters

    def output_path(self, metadata: BookMetadata, fmt: str) -> Path:
        self.ensure_book_dirs(metadata.book_id)
        return self.outputs_dir(metadata.book_id) / f"{metadata.safe_title}.{fmt}"

    def package_path(self, metadata: BookMetadata) -> Path:
        self.ensure_book_dirs(metadata.book_id)
        return self.packages_dir(metadata.book_id) / f"{metadata.safe_title}.zip"

    def chapter_fingerprint(self, chapters: list[ChapterTask]) -> str:
        raw = "\n".join(f"{chapter.index}|{chapter.title}|{chapter.url}" for chapter in chapters)
        return sha256(raw.encode("utf-8")).hexdigest()

    def needs_download(self, book_id: str, chapters: list[ChapterTask], fmt: str) -> tuple[bool, str]:
        status = self.load_status(book_id)
        if not status:
            return True, "missing"
        remote_fp = self.chapter_fingerprint(chapters)
        if status.get("chapter_fingerprint") != remote_fp:
            return True, "changed"
        if fmt not in status.get("downloaded_formats", []):
            return False, "missing_format"
        return False, "reuse"

    def clear_book_content_for_redownload(self, book_id: str) -> None:
        for sub in ("chapters", "illustrations", "outputs", "packages"):
            path = self.book_dir(book_id) / sub
            if path.exists():
                shutil.rmtree(path)
        self.ensure_book_dirs(book_id)

    def clear_book(self, book_id: str) -> bool:
        path = self.book_dir(book_id)
        if path.exists():
            shutil.rmtree(path)
            return True
        return False

    def clear_outputs(self) -> int:
        count = 0
        for book in self.books_dir.iterdir():
            if not book.is_dir():
                continue
            for name in ("outputs", "packages"):
                path = book / name
                if path.exists():
                    shutil.rmtree(path)
                    path.mkdir(parents=True, exist_ok=True)
                    count += 1
        return count

    def clear_cache(self) -> int:
        count = 0
        for book in self.books_dir.iterdir():
            if not book.is_dir():
                continue
            path = book / "chapters"
            if path.exists():
                shutil.rmtree(path)
                path.mkdir(parents=True, exist_ok=True)
                count += 1
        return count

    def list_books(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        if not self.books_dir.exists():
            return result
        for book in sorted(self.books_dir.iterdir()):
            status_path = book / "status.json"
            if status_path.exists():
                result.append(json.loads(status_path.read_text(encoding="utf-8")))
        return result
