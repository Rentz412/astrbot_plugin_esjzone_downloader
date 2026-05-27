from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .models import BookMetadata, ChapterData, ChapterTask, EsjUrlType
from .utils import ALLOWED_ESJ_HOSTS, EsjSecurityError, safe_filename, validate_esj_url


DETAIL_RE = re.compile(r"^/detail/(\d+)\.html$")
FORUM_INDEX_RE = re.compile(r"^/forum/(\d+)/?$")
CHAPTER_RE = re.compile(r"^/forum/(\d+)/([^/]+)\.html$")


class EsjParser:
    def normalize_input(self, raw: str) -> tuple[str, str, EsjUrlType]:
        value = (raw or "").strip()
        if not value:
            raise ValueError("请输入 ESJZone 小说编号或 URL")

        if value.isdigit():
            book_id = value
            url = f"https://www.esjzone.one/detail/{book_id}.html"
            return book_id, url, EsjUrlType.DETAIL

        validate_esj_url(value)
        parsed = urlparse(value)
        if parsed.hostname not in ALLOWED_ESJ_HOSTS:
            raise EsjSecurityError("URL 域名不在白名单内")

        detail = DETAIL_RE.match(parsed.path)
        if detail:
            return detail.group(1), value, EsjUrlType.DETAIL

        forum = FORUM_INDEX_RE.match(parsed.path)
        if forum:
            return forum.group(1), value, EsjUrlType.FORUM_INDEX

        chapter = CHAPTER_RE.match(parsed.path)
        if chapter:
            return chapter.group(1), value, EsjUrlType.CHAPTER

        raise ValueError("不支持的 ESJZone URL 格式")

    def build_detail_url(self, book_id: str) -> str:
        return f"https://www.esjzone.one/detail/{book_id}.html"

    def build_forum_url(self, book_id: str) -> str:
        return f"https://www.esjzone.one/forum/{book_id}"

    def parse_book_metadata(self, html: str, book_id: str, source_url: str) -> BookMetadata:
        soup = BeautifulSoup(html, "lxml")

        title = ""
        title_node = soup.select_one(".book-detail h2.text-normal")
        if title_node:
            title = title_node.get_text(" ", strip=True)
        if not title and soup.title:
            title = soup.title.get_text(" ", strip=True)
        title = title or f"ESJZone_{book_id}"

        author = "未知作者"
        detail_items = soup.select(".book-detail ul.book-detail li")
        info_lines: list[str] = []
        for item in detail_items:
            text = item.get_text(" ", strip=True)
            if text:
                info_lines.append(text)
            if "作者" in text or "作家" in text:
                author = re.sub(r"^(作者|作家)\s*[:：]?\s*", "", text).strip() or author

        intro = ""
        intro_node = soup.select_one("#details .description")
        if intro_node:
            intro = intro_node.get_text("\n", strip=True)

        cover_url = None
        cover_node = soup.select_one(".product-gallery img[src]")
        if cover_node and cover_node.get("src"):
            cover_url = urljoin(source_url, cover_node["src"])
            try:
                validate_esj_url(cover_url)
            except EsjSecurityError:
                cover_url = None

        return BookMetadata(
            book_id=book_id,
            title=title,
            safe_title=safe_filename(title, fallback=f"esj_{book_id}"),
            author=author,
            detail_url=self.build_detail_url(book_id),
            forum_url=self.build_forum_url(book_id),
            cover_url=cover_url,
            intro_text=intro,
            info_block="\n".join(info_lines),
        )

    def parse_chapter_list(self, html: str, base_url: str) -> list[ChapterTask]:
        soup = BeautifulSoup(html, "lxml")
        tasks: list[ChapterTask] = []
        seen: set[str] = set()

        for node in soup.select("#chapterList a[href], a[href]"):
            href = node.get("href", "").strip()
            if not href:
                continue
            absolute = urljoin(base_url, href)
            parsed = urlparse(absolute)
            is_external = parsed.hostname not in ALLOWED_ESJ_HOSTS
            if not is_external:
                if not CHAPTER_RE.match(parsed.path):
                    continue
                try:
                    validate_esj_url(absolute)
                except EsjSecurityError:
                    continue
            if absolute in seen:
                continue
            seen.add(absolute)
            title = node.get_text(" ", strip=True) or f"第 {len(tasks) + 1} 章"
            tasks.append(
                ChapterTask(
                    index=len(tasks),
                    title=title,
                    url=absolute,
                    is_external=is_external,
                )
            )

        return tasks

    def parse_chapter_html(self, html: str, task: ChapterTask) -> ChapterData:
        if task.is_external:
            text = f"本章为非站内链接，插件未抓取正文：{task.url}"
            return ChapterData(
                index=task.index,
                title=task.title,
                author="",
                content_html=f"<p>{text}</p>",
                content_text=text,
                txt_segment=f"{task.title}\n\n{text}\n",
            )

        soup = BeautifulSoup(html, "lxml")
        title_node = soup.select_one("h2")
        title = title_node.get_text(" ", strip=True) if title_node else task.title

        author = ""
        author_node = soup.select_one(".single-post-meta div")
        if author_node:
            author = author_node.get_text(" ", strip=True)

        content_node = soup.select_one(".forum-content")
        if not content_node:
            raise ValueError(f"章节正文不存在：{task.title}")

        content_html = str(content_node)
        content_text = content_node.get_text("\n", strip=True)

        if content_text.startswith(title):
            content_text = content_text[len(title) :].lstrip()

        txt_segment = f"{title}\n"
        if author:
            txt_segment += f"作者：{author}\n"
        txt_segment += f"\n{content_text}\n"

        return ChapterData(
            index=task.index,
            title=title or task.title,
            author=author,
            content_html=content_html,
            content_text=content_text,
            txt_segment=txt_segment,
        )
