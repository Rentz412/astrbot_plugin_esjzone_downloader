"""ESJZone 下载器的数据模型定义。

集中放置 URL、书籍、章节、认证、下载结果与任务状态等结构，降低模块之间传参的耦合度。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal


class EsjUrlType(Enum):
    """标识用户输入对应的 ESJZone URL 类型。"""
    DETAIL = "detail"
    CHAPTER = "chapter"


@dataclass(slots=True)
class NormalizedEsjUrl:
    """用户输入规范化后的详情页/目录页信息。"""
    url_type: EsjUrlType
    book_id: str
    detail_url: str
    source_url: str
    chapter_id: str | None = None
    chapter_url: str | None = None
    host: str = "www.esjzone.one"


@dataclass(slots=True)
class BookMetadata:
    """书籍级元数据，贯穿下载、导出和状态展示流程。"""
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
    """待下载章节的轻量任务描述。"""
    index: int
    chapter_id: str
    title: str
    url: str


@dataclass(slots=True)
class ChapterContent:
    """已下载并解析完成的章节正文数据。"""
    chapter: ChapterTask
    title: str
    author: str = ""
    html: str = ""
    text: str = ""


@dataclass(slots=True)
class CookieValidationResult:
    """Cookie 校验结果及识别出的用户名。"""
    valid: bool
    username: str | None = None
    unknown: bool = False
    reason: str = ""


@dataclass(slots=True)
class AuthResult:
    """登录或刷新认证后的结果对象。"""
    success: bool
    username: str | None = None
    cookie_header: str = ""
    cookie_jar: list[dict[str, Any]] = field(default_factory=list)
    reason: str = ""


@dataclass(slots=True)
class AuthContext:
    """执行下载请求时需要的认证上下文。"""
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
    """下载与打包完成后返回给命令层的结果。"""
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
    """用于展示或持久化下载任务进度的状态对象。"""
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
