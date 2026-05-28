from __future__ import annotations

import json
import shutil
import time
from hashlib import sha256
from pathlib import Path

from .models import BookMetadata, ChapterContent, ChapterTask


class EsjRepository:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.books_dir = data_dir / "books"
        self.books_dir.mkdir(parents=True, exist_ok=True)

    def book_dir(self, book_id: str) -> Path:
        path = self.books_dir / book_id
        path.mkdir(parents=True, exist_ok=True)
        for child in ("chapters", "outputs", "packages", "logs", "illustrations"):
            (path / child).mkdir(exist_ok=True)
        return path

    def status_path(self, book_id: str) -> Path:
        return self.book_dir(book_id) / "status.json"

    def metadata_path(self, book_id: str) -> Path:
        return self.book_dir(book_id) / "metadata.json"

    def load_status(self, book_id: str) -> dict | None:
        path = self.status_path(book_id)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def save_metadata(self, metadata: BookMetadata) -> None:
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

    def save_status(
        self,
        metadata: BookMetadata,
        chapters: list[ChapterTask],
        fmt: str,
        package_path: Path,
        failed_chapters: int = 0,
        failed_images: int = 0,
        has_cover: bool = False,
        illustration_count: int = 0,
    ) -> None:
        existing = self.load_status(metadata.book_id) or {}
        formats = set(existing.get("downloaded_formats", []))
        formats.add(fmt)
        latest = chapters[-1] if chapters else None
        payload = {
            "version": 1,
            "book_id": metadata.book_id,
            "title": metadata.title,
            "author": metadata.author,
            "source_url": metadata.detail_url,
            "detail_url": metadata.detail_url,
            "forum_url": None,
            "chapter_count": len(chapters),
            "latest_chapter_title": latest.title if latest else "",
            "latest_chapter_url": latest.url if latest else "",
            "chapter_fingerprint": self.fingerprint(chapters),
            "last_remote_check_at": int(time.time()),
            "last_download_at": int(time.time()),
            "downloaded_formats": sorted(formats),
            "package_path": str(package_path.relative_to(self.book_dir(metadata.book_id))).replace("\\", "/"),
            "has_cover": has_cover,
            "illustration_count": illustration_count,
            "failed_chapters": failed_chapters,
            "failed_images": failed_images,
        }
        self.status_path(metadata.book_id).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def fingerprint(chapters: list[ChapterTask]) -> str:
        raw = "\n".join(f"{idx}|{c.title}|{c.url}" for idx, c in enumerate(chapters))
        return sha256(raw.encode("utf-8")).hexdigest()

    def chapter_cache_path(self, book_id: str, chapter: ChapterTask) -> Path:
        return self.book_dir(book_id) / "chapters" / f"{chapter.index + 1:04d}_{chapter.chapter_id}.json"

    def save_chapter(self, book_id: str, content: ChapterContent) -> None:
        payload = {
            "index": content.chapter.index,
            "chapter_id": content.chapter.chapter_id,
            "title": content.title,
            "url": content.chapter.url,
            "author": content.author,
            "html": content.html,
            "text": content.text,
        }
        self.chapter_cache_path(book_id, content.chapter).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def load_chapters(self, book_id: str) -> list[dict]:
        rows = []
        for path in sorted((self.book_dir(book_id) / "chapters").glob("*.json")):
            rows.append(json.loads(path.read_text(encoding="utf-8")))
        return rows

    def clear_book_runtime(self, book_id: str) -> None:
        root = self.book_dir(book_id)
        for name in ("chapters", "outputs", "packages", "illustrations"):
            target = root / name
            if target.exists():
                shutil.rmtree(target)
            target.mkdir(exist_ok=True)

    def list_books(self) -> list[dict]:
        books = []
        for path in sorted(self.books_dir.iterdir()):
            if path.is_dir() and (path / "status.json").exists():
                books.append(json.loads((path / "status.json").read_text(encoding="utf-8")))
        return books

    def clear_cache(self) -> int:
        count = 0
        for path in self.books_dir.glob("*/chapters"):
            shutil.rmtree(path, ignore_errors=True)
            path.mkdir(parents=True, exist_ok=True)
            count += 1
        return count

    def clear_outputs(self) -> int:
        count = 0
        for pattern in ("*/outputs", "*/packages"):
            for path in self.books_dir.glob(pattern):
                shutil.rmtree(path, ignore_errors=True)
                path.mkdir(parents=True, exist_ok=True)
                count += 1
        return count

    def clear_book(self, book_id: str) -> bool:
        path = self.books_dir / book_id
        if path.exists():
            shutil.rmtree(path)
            return True
        return False
