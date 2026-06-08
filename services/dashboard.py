"""ESJZone 下载器 Dashboard 数据服务。

本模块负责扫描插件数据目录，生成 Plugin Page 使用的缓存快照，
并集中处理 Dashboard 上的清理、删除等文件操作。
"""

from __future__ import annotations

import json
import mimetypes
import shutil
import time
from pathlib import Path
from typing import Any


class DashboardService:
    """构建并维护 Dashboard 缓存数据。"""

    OUTPUT_EXTENSIONS = {".txt", ".epub"}

    def __init__(self, data_dir: Path, plugin_dir: Path):
        self.data_dir = data_dir
        self.plugin_dir = plugin_dir
        self.books_dir = data_dir / "books"
        self.auth_users_dir = data_dir / "auth" / "users"
        self.debug_dir = data_dir / "debug"
        self.cache_path = data_dir / "dashboard_cache.json"

    def load_cache(self) -> dict[str, Any]:
        """读取 Dashboard 缓存；缓存缺失或损坏时自动重新生成。"""
        if self.cache_path.exists():
            try:
                payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    return payload
            except Exception:
                pass
        return self.refresh_cache()

    def refresh_cache(self) -> dict[str, Any]:
        """从本地文件重新扫描并生成 Dashboard 缓存。"""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.books_dir.mkdir(parents=True, exist_ok=True)

        books = self._scan_books()
        debug_stats = self._scan_debug()
        payload = {
            "version": 1,
            "generated_at": int(time.time()),
            "summary": {
                "logged_in_users": self._count_logged_in_users(),
                "local_books": len(books),
                "data_dir_size": self._dir_size(self.data_dir),
                "debug_file_count": debug_stats["file_count"],
                "debug_size": debug_stats["size"],
            },
            "debug": debug_stats,
            "books": books,
            "plugin": self._plugin_metadata(),
        }
        self.cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload

    def get_book(self, book_id: str) -> dict[str, Any] | None:
        """从缓存中返回单本书信息；必要时会触发缓存生成。"""
        cache = self.load_cache()
        for book in cache.get("books", []):
            if str(book.get("book_id")) == str(book_id):
                return book
        return None

    def cover_path(self, book_id: str) -> Path | None:
        """解析单本书的封面文件路径。"""
        root = self._book_root(book_id)
        if not root or not root.exists():
            return None

        metadata = self._read_json(root / "metadata.json")
        # 优先使用 metadata 中记录的封面文件名，避免依赖扩展名猜测。
        cover_name = str(metadata.get("cover_path") or "").strip()
        if cover_name:
            cover = self._safe_child_file(root, cover_name)
            if cover:
                return cover

        # 兼容旧数据：没有 cover_path 时回退查找 cover.*。
        for candidate in sorted(root.glob("cover.*")):
            if candidate.is_file():
                return candidate
        return None

    def logo_path(self) -> Path | None:
        """返回插件 Logo 文件路径。"""
        path = self.plugin_dir / "logo.png"
        return path if path.exists() and path.is_file() else None

    def clear_book_files(self, book_id: str) -> dict[str, Any]:
        """删除单本书导出的 TXT/EPUB 文件及其 manifest。"""
        root = self._book_root(book_id)
        deleted = self._clear_output_files(root / "outputs") if root else 0
        self.refresh_cache()
        return {"deleted": deleted, "book_id": book_id}

    def delete_book(self, book_id: str) -> dict[str, Any]:
        """删除单本书的整个本地缓存目录。"""
        root = self._book_root(book_id)
        deleted = False
        if root and root.exists() and root.is_dir():
            shutil.rmtree(root)
            deleted = True
        self.refresh_cache()
        return {"deleted": deleted, "book_id": book_id}

    def clear_all_book_files(self) -> dict[str, Any]:
        """删除所有书籍的导出文件和 manifest，保留章节、封面等缓存。"""
        deleted = 0
        if self.books_dir.exists():
            for root in self.books_dir.iterdir():
                if root.is_dir():
                    deleted += self._clear_output_files(root / "outputs")
        self.refresh_cache()
        return {"deleted": deleted}

    def delete_all_books(self) -> dict[str, Any]:
        """删除全部本地书籍数据，并保留 books 根目录。"""
        deleted = 0
        if self.books_dir.exists():
            for root in self.books_dir.iterdir():
                if root.is_dir():
                    shutil.rmtree(root)
                    deleted += 1
        self.books_dir.mkdir(parents=True, exist_ok=True)
        self.refresh_cache()
        return {"deleted": deleted}

    def clear_debug(self) -> dict[str, Any]:
        """清理调试文件，同时保留 debug 子目录结构。"""
        deleted = 0
        for name in ("auth", "pages"):
            target = self.debug_dir / name
            if target.exists():
                deleted += self._clear_directory_contents(target)
            target.mkdir(parents=True, exist_ok=True)
        self.refresh_cache()
        return {"deleted": deleted}

    def _scan_books(self) -> list[dict[str, Any]]:
        """扫描 books/ 下的每个书籍目录并汇总为前端需要的字段。"""
        books: list[dict[str, Any]] = []
        if not self.books_dir.exists():
            return books

        for root in sorted(self.books_dir.iterdir()):
            if not root.is_dir():
                continue
            # status 记录下载/导出状态，metadata 记录书籍基础信息。
            status = self._read_json(root / "status.json")
            metadata = self._read_json(root / "metadata.json")
            if not status and not metadata:
                continue

            book_id = str(status.get("book_id") or metadata.get("book_id") or root.name)
            outputs = self._scan_outputs(root / "outputs")
            chapters_dir = root / "chapters"
            illustrations_dir = root / "illustrations"
            packages_dir = root / "packages"

            title = str(status.get("title") or metadata.get("title") or book_id)
            author = str(status.get("author") or metadata.get("author") or "未知作者")
            # cover_url 是前端使用的逻辑端点；实际图片读取由 main.py 的 cover/cover-data 路由完成。
            book = {
                "book_id": book_id,
                "title": title,
                "safe_title": metadata.get("safe_title") or title,
                "author": author,
                "description": metadata.get("description") or "",
                "info_block": metadata.get("info_block") or "",
                "source_url": status.get("source_url") or metadata.get("source_url") or "",
                "detail_url": status.get("detail_url") or metadata.get("source_url") or "",
                "forum_url": status.get("forum_url"),
                "chapter_count": int(status.get("chapter_count") or 0),
                "cached_chapter_count": self._count_files(chapters_dir, "*.json"),
                "latest_chapter_title": status.get("latest_chapter_title") or "",
                "latest_chapter_url": status.get("latest_chapter_url") or "",
                "chapter_fingerprint": status.get("chapter_fingerprint") or "",
                "last_remote_check_at": status.get("last_remote_check_at"),
                "last_download_at": status.get("last_download_at"),
                "created_at": metadata.get("created_at"),
                "updated_at": metadata.get("updated_at"),
                "downloaded_formats": status.get("downloaded_formats") or [],
                "package_path": status.get("package_path") or "",
                "has_cover": bool(status.get("has_cover") or self.cover_path(book_id)),
                "cover_url": f"dashboard/books/{book_id}/cover",
                "illustration_count": int(status.get("illustration_count") or self._count_files(illustrations_dir, "*")),
                "failed_chapters": int(status.get("failed_chapters") or 0),
                "failed_images": int(status.get("failed_images") or 0),
                "outputs": outputs,
                "output_size": sum(item["size"] for item in outputs),
                "package_count": self._count_files(packages_dir, "*"),
                "package_size": self._dir_size(packages_dir),
                "book_size": self._dir_size(root),
                "status": self._status_label(status),
                "status_raw": status,
                "metadata_raw": metadata,
            }
            books.append(book)

        books.sort(key=lambda item: int(item.get("last_download_at") or item.get("updated_at") or 0), reverse=True)
        return books

    def _scan_outputs(self, outputs_dir: Path) -> list[dict[str, Any]]:
        """扫描导出目录中的 TXT/EPUB 文件。"""
        rows: list[dict[str, Any]] = []
        if not outputs_dir.exists():
            return rows
        for path in sorted(outputs_dir.iterdir()):
            if not path.is_file() or path.suffix.lower() not in self.OUTPUT_EXTENSIONS:
                continue
            manifest_path = path.with_name(f"{path.name}.manifest.json")
            rows.append({
                "name": path.name,
                "format": path.suffix.lower().lstrip("."),
                "size": path.stat().st_size,
                "modified_at": int(path.stat().st_mtime),
                "has_manifest": manifest_path.exists(),
                "manifest_name": manifest_path.name if manifest_path.exists() else "",
            })
        return rows

    def _scan_debug(self) -> dict[str, Any]:
        """统计 debug 目录的文件数量和占用空间。"""
        return {
            "path": str(self.debug_dir),
            "file_count": self._count_files(self.debug_dir, "*"),
            "size": self._dir_size(self.debug_dir),
            "auth_size": self._dir_size(self.debug_dir / "auth"),
            "pages_size": self._dir_size(self.debug_dir / "pages"),
        }

    def _plugin_metadata(self) -> dict[str, Any]:
        """返回 Dashboard 顶部栏展示的插件元信息。"""
        return {
            "name": "astrbot_plugin_esjzone_downloader",
            "display_name": "ESJZone 小说下载器",
            "version": "v2.3.0",
            "author": "Rentz",
            "repo": "https://github.com/Rentz412/astrbot_plugin_esjzone_downloader",
            "logo_url": "dashboard/logo",
        }

    @staticmethod
    def _status_label(status: dict[str, Any]) -> str:
        if int(status.get("failed_chapters") or 0) > 0 or int(status.get("failed_images") or 0) > 0:
            return "warning"
        formats = status.get("downloaded_formats") or []
        if formats:
            return "ready"
        return "cached"

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        if not path.exists() or not path.is_file():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _dir_size(path: Path) -> int:
        if not path.exists():
            return 0
        if path.is_file():
            try:
                return path.stat().st_size
            except OSError:
                return 0

        total = 0
        for child in path.rglob("*"):
            if child.is_file():
                try:
                    total += child.stat().st_size
                except OSError:
                    pass
        return total

    @staticmethod
    def _count_files(path: Path, pattern: str) -> int:
        if not path.exists():
            return 0
        return sum(1 for item in path.rglob(pattern) if item.is_file())

    def _count_logged_in_users(self) -> int:
        if not self.auth_users_dir.exists():
            return 0
        return sum(1 for item in self.auth_users_dir.glob("*.json") if item.is_file())

    def _book_root(self, book_id: str) -> Path | None:
        """安全解析书籍目录，防止通过 book_id 访问 books/ 之外的路径。"""
        book_name = str(book_id).strip()
        if not book_name or book_name in {".", ".."}:
            return None

        books_root = self.books_dir.resolve()
        root = (self.books_dir / book_name).resolve()
        try:
            root.relative_to(books_root)
        except ValueError:
            return None
        return root

    @staticmethod
    def _safe_child_file(root: Path, name: str) -> Path | None:
        """安全解析 root 下的文件名，拒绝绝对路径和目录穿越。"""
        if not name:
            return None
        root_resolved = root.resolve()
        path = (root / name).resolve()
        try:
            path.relative_to(root_resolved)
        except ValueError:
            return None
        return path if path.exists() and path.is_file() else None

    def _clear_output_files(self, outputs_dir: Path) -> int:
        """仅清理导出产物，不删除章节缓存、封面和插图。"""
        if not outputs_dir.exists():
            return 0
        deleted = 0
        targets: list[Path] = []
        for path in outputs_dir.iterdir():
            if not path.is_file():
                continue
            name = path.name.lower()
            if path.suffix.lower() in self.OUTPUT_EXTENSIONS:
                targets.append(path)
                manifest = path.with_name(f"{path.name}.manifest.json")
                if manifest.exists() and manifest.is_file():
                    targets.append(manifest)
            elif name.endswith(".txt.manifest.json") or name.endswith(".epub.manifest.json"):
                targets.append(path)

        seen: set[Path] = set()
        for path in targets:
            if path in seen:
                continue
            seen.add(path)
            try:
                path.unlink()
                deleted += 1
            except FileNotFoundError:
                pass
        return deleted

    @staticmethod
    def _clear_directory_contents(path: Path) -> int:
        deleted = 0
        for child in path.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
                deleted += 1
            else:
                child.unlink()
                deleted += 1
        return deleted


def guess_mime(path: Path) -> str:
    """根据文件名推断静态资源的 MIME 类型。"""
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"
