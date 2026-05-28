from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal


class EsjUrlType(Enum):
    DETAIL = "detail"
    CHAPTER = "chapter"


@dataclass(slots=True)
class NormalizedEsjUrl:
    url_type: EsjUrlType
    book_id: str
    detail_url: str
    source_url: str
    chapter_id: str | None = None
    chapter_url: str | None = None
    host: str = "www.esjzone.one"


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
    chapter_id: str
    title: str
    url: str


@dataclass(slots=True)
class ChapterContent:
    chapter: ChapterTask
    title: str
    author: str = ""
    html: str = ""
    text: str = ""


@dataclass(slots=True)
class CookieValidationResult:
    valid: bool
    username: str | None = None
    unknown: bool = False
    reason: str = ""


@dataclass(slots=True)
class AuthResult:
    success: bool
    username: str | None = None
    cookie_header: str = ""
    cookie_jar: list[dict[str, Any]] = field(default_factory=list)
    reason: str = ""


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
class DownloadResult:
    book_id: str
    title: str
    output_path: str
    package_path: str
    password: str
    reused: bool = False
    format: str = "epub"
    chapter_count: int = 0


@dataclass(slots=True)
class DownloadTaskState:
    task_id: str
    book_id: str
    url: str
    format: str
    total: int
    completed: int = 0
    failed_chapters: int = 0
    failed_images: int = 0
    status: Literal["pending", "running", "cancelled", "failed", "completed"] = "pending"
    created_at: float = 0
    updated_at: float = 0
