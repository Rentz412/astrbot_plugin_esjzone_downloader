from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Literal


class EsjUrlType(Enum):
    DETAIL = "detail"
    FORUM_INDEX = "forum_index"
    CHAPTER = "chapter"


@dataclass(slots=True)
class BookMetadata:
    book_id: str
    title: str
    safe_title: str
    author: str
    detail_url: str
    forum_url: str | None = None
    cover_url: str | None = None
    intro_text: str = ""
    info_block: str = ""


@dataclass(slots=True)
class ChapterTask:
    index: int
    title: str
    url: str
    is_external: bool = False


@dataclass(slots=True)
class ImageData:
    id: str
    source_url: str
    file_path: str
    media_type: str
    size: int


@dataclass(slots=True)
class ChapterData:
    index: int
    title: str
    author: str
    content_html: str
    content_text: str
    txt_segment: str
    images: list[ImageData] = field(default_factory=list)
    image_errors: int = 0
    error: str | None = None


@dataclass(slots=True)
class AuthContext:
    user_hash: str
    platform_id: str
    sender_id: str
    cookie: str
    cookie_jar: list[dict[str, Any]] | None = None
    email_masked: str | None = None
    username: str | None = None
    login_valid: bool = True
    refreshed: bool = False


@dataclass(slots=True)
class AuthResult:
    success: bool
    message: str
    cookie: str = ""
    cookie_jar: list[dict[str, Any]] = field(default_factory=list)
    username: str | None = None


@dataclass(slots=True)
class CookieValidationResult:
    valid: bool
    unknown: bool = False
    username: str | None = None
    message: str = ""


@dataclass(slots=True)
class DownloadTaskState:
    task_id: str
    book_id: str
    url: str
    format: str
    total: int = 0
    completed: int = 0
    failed_chapters: int = 0
    failed_images: int = 0
    status: Literal["pending", "running", "cancelled", "failed", "completed"] = "pending"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


@dataclass(slots=True)
class DownloadResult:
    book_id: str
    title: str
    output_path: Path
    package_path: Path
    zip_password: str
    reused: bool = False
    format: str = "epub"
    failed_chapters: int = 0
    failed_images: int = 0


@dataclass(slots=True)
class DownloadOptions:
    fmt: Literal["epub", "txt"] = "epub"
    start: int = 0
    end: int = 0
    force: bool = False
