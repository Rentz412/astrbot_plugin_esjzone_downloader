"""ESJZone 页面解析工具。

负责标准化用户输入、解析书籍详情页和章节页，并将站点 HTML 转换为内部数据模型。"""

from __future__ import annotations

import re
from html import unescape
from pathlib import Path
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .models import BookMetadata, ChapterContent, ChapterTask, EsjUrlType, NormalizedEsjUrl

BASE_URL = "https://www.esjzone.one"
BACKUP_URL = "https://www.esjzone.cc"
ALLOWED_ESJ_HOSTS = {"www.esjzone.one", "www.esjzone.cc"}

DETAIL_RE = re.compile(r"^/detail/(\d+)(?:\.html)?/?$")
CHAPTER_RE = re.compile(r"^/forum/(\d+)/(\d+)(?:\.html)?/?$")
DIGITS_RE = re.compile(r"^\d+$")


def safe_filename(name: str, max_len: int = 120) -> str:
    """清理文件名中的非法字符并限制长度。"""
    cleaned = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", name).strip(" ._")
    cleaned = cleaned or "untitled"
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
    if cleaned.upper() in reserved:
        cleaned = f"_{cleaned}"
    return cleaned[:max_len]


def normalize_esj_input(raw: str) -> NormalizedEsjUrl:
    """将编号、详情页或目录页输入统一成详情页 URL。"""
    value = (raw or "").strip()
    if not value:
        raise ValueError("URL 或书籍编号不能为空")

    if DIGITS_RE.fullmatch(value):
        book_id = value
        detail_url = f"{BASE_URL}/detail/{book_id}.html"
        return NormalizedEsjUrl(
            url_type=EsjUrlType.DETAIL,
            book_id=book_id,
            detail_url=detail_url,
            source_url=value,
        )

    if "\\" in value or any(ord(c) < 32 for c in value):
        raise ValueError("URL 包含非法字符")

    parsed = urlparse(value)
    if parsed.scheme != "https":
        raise ValueError("只允许 https URL")
    if parsed.hostname not in ALLOWED_ESJ_HOSTS:
        raise ValueError("只允许 www.esjzone.one 或 www.esjzone.cc")
    if parsed.username or parsed.password:
        raise ValueError("URL 不允许包含用户名或密码")

    detail_match = DETAIL_RE.fullmatch(parsed.path)
    if detail_match:
        book_id = detail_match.group(1)
        detail_url = f"{BASE_URL}/detail/{book_id}.html"
        return NormalizedEsjUrl(
            url_type=EsjUrlType.DETAIL,
            book_id=book_id,
            detail_url=detail_url,
            source_url=value,
            host="www.esjzone.one",
        )

    chapter_match = CHAPTER_RE.fullmatch(parsed.path)
    if chapter_match:
        book_id, chapter_id = chapter_match.groups()
        detail_url = f"{BASE_URL}/detail/{book_id}.html"
        chapter_url = f"{BASE_URL}/forum/{book_id}/{chapter_id}.html"
        return NormalizedEsjUrl(
            url_type=EsjUrlType.CHAPTER,
            book_id=book_id,
            chapter_id=chapter_id,
            detail_url=detail_url,
            chapter_url=chapter_url,
            source_url=value,
            host="www.esjzone.one",
        )

    forum_book = re.fullmatch(r"^/forum/(\d+)(?:\.html)?/?$", parsed.path)
    if forum_book:
        raise ValueError("/forum/<书籍编号> 不是有效书籍目录页，请使用 /detail/<书籍编号> 或章节页 /forum/<书籍编号>/<章节编号>")

    detail_with_chapter = re.fullmatch(r"^/detail/(\d+)/([^/]+?)(?:\.html)?/?$", parsed.path)
    if detail_with_chapter:
        raise ValueError("/detail/<书籍编号>/<章节编号> 不是有效详情页，请使用 /detail/<书籍编号>")

    raise ValueError("不支持的 ESJZone URL 格式")


def _text(node) -> str:
    """提取节点文本并压缩多余空白。"""
    if not node:
        return ""
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()


def parse_book_detail(html: str, normalized: NormalizedEsjUrl) -> tuple[BookMetadata, list[ChapterTask]]:
    """解析详情页中的书籍元数据和章节任务列表。"""
    soup = BeautifulSoup(html, "lxml")

    title = _text(soup.select_one(".book-detail h2.text-normal"))
    if not title:
        title = _text(soup.select_one("title")).replace(" - ESJ Zone", "").strip()
    title = title or f"ESJZone_{normalized.book_id}"

    info_nodes = soup.select(".book-detail ul.book-detail li")
    info_block = "\n".join(_text(n) for n in info_nodes if _text(n))
    author = ""
    for line in info_block.splitlines():
        if "作者" in line or "作家" in line:
            author = re.sub(r"^(作者|作家)\s*[:：]?\s*", "", line).strip()
            break
    author = author or "未知作者"

    intro = _text(soup.select_one("#details .description")) or _text(soup.select_one(".description"))

    cover_url = None
    cover = soup.select_one(".product-gallery img[src]")
    if cover and cover.get("src"):
        cover_url = normalize_asset_url(cover.get("src"), normalized.detail_url)

    chapters: list[ChapterTask] = []
    seen: set[str] = set()
    for link in soup.select("#chapterList a[href], a[href]"):
        href = link.get("href", "").strip()
        abs_url = normalize_asset_url(href, normalized.detail_url)
        parsed = urlparse(abs_url)
        match = CHAPTER_RE.fullmatch(parsed.path)
        if not match:
            continue
        book_id, chapter_id = match.groups()
        if book_id != normalized.book_id:
            continue
        chapter_url = f"{BASE_URL}/forum/{book_id}/{chapter_id}.html"
        if chapter_url in seen:
            continue
        seen.add(chapter_url)
        chapter_title = _text(link) or f"第 {len(chapters) + 1} 章"
        chapters.append(ChapterTask(index=len(chapters), chapter_id=chapter_id, title=chapter_title, url=chapter_url))

    metadata = BookMetadata(
        book_id=normalized.book_id,
        title=title,
        safe_title=safe_filename(title),
        author=author,
        detail_url=normalized.detail_url,
        cover_url=cover_url,
        intro_text=intro,
        info_block=info_block,
    )
    return metadata, chapters


def normalize_asset_url(url: str, base: str = BASE_URL) -> str:
    """将图片等资源地址标准化为绝对 URL。"""
    value = unescape((url or "").strip())
    if not value:
        return ""
    abs_url = urljoin(base, value)
    parsed = urlparse(abs_url)
    if parsed.scheme not in {"https", "http"}:
        return ""
    if parsed.hostname in ALLOWED_ESJ_HOSTS:
        path = parsed.path
        return f"{BASE_URL}{path}"
    return abs_url


def parse_chapter_content(html: str, chapter: ChapterTask) -> ChapterContent:
    """解析章节页正文、标题、作者和文本内容。"""
    soup = BeautifulSoup(html, "lxml")
    title = _text(soup.select_one("h2")) or chapter.title
    author = _text(soup.select_one(".single-post-meta div"))
    content = soup.select_one(".forum-content")
    if not content:
        raise ValueError(f"章节正文缺失: {chapter.title}")

    for bad in content.select("script, style"):
        bad.decompose()

    html_body = str(content)
    text_body = content.get_text("\n", strip=True)
    text_body = re.sub(r"\n{3,}", "\n\n", text_body).strip()
    if text_body.startswith(title):
        text_body = text_body[len(title):].lstrip()

    return ChapterContent(chapter=chapter, title=title, author=author, html=html_body, text=text_body)
