from __future__ import annotations

from pathlib import Path

from bs4 import BeautifulSoup
from ebooklib import epub

from .models import BookMetadata, ChapterData


class EpubExporter:
    async def export(
        self,
        metadata: BookMetadata,
        chapters: list[ChapterData],
        output_path: Path,
        cover_path: Path | None = None,
    ) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)

        book = epub.EpubBook()
        book.set_identifier(f"esjzone-{metadata.book_id}")
        book.set_title(metadata.title)
        book.set_language("zh-CN")
        book.add_author(metadata.author or "未知作者")

        if cover_path and cover_path.exists():
            book.set_cover(cover_path.name, cover_path.read_bytes())

        intro = epub.EpubHtml(title="简介", file_name="intro.xhtml", lang="zh-CN")
        intro.content = self._wrap_xhtml("简介", f"<h1>{metadata.title}</h1><p>{metadata.intro_text or '无简介'}</p>")
        book.add_item(intro)

        epub_chapters: list[epub.EpubHtml] = []
        for chapter in sorted(chapters, key=lambda item: item.index):
            item = epub.EpubHtml(
                title=chapter.title,
                file_name=f"chapters/chapter_{chapter.index + 1:05d}.xhtml",
                lang="zh-CN",
            )
            item.content = self._wrap_xhtml(chapter.title, self._clean_html(chapter.content_html))
            book.add_item(item)
            epub_chapters.append(item)

        book.toc = [intro, *epub_chapters]
        book.spine = ["nav", intro, *epub_chapters]
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())

        epub.write_epub(str(output_path), book)
        return output_path

    def _clean_html(self, html: str) -> str:
        soup = BeautifulSoup(html or "", "lxml")
        body = soup.body or soup
        for tag in body.find_all(True):
            allowed_attrs = {}
            if tag.name == "img" and tag.get("src"):
                allowed_attrs["src"] = tag["src"]
                if tag.get("alt"):
                    allowed_attrs["alt"] = tag["alt"]
            tag.attrs = allowed_attrs
        return "".join(str(child) for child in body.children)

    def _wrap_xhtml(self, title: str, body_html: str) -> str:
        return f"""<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" lang="zh-CN">
<head>
  <title>{title}</title>
</head>
<body>
{body_html}
</body>
</html>"""
