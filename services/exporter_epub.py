"""EPUB 导出模块。

将已缓存的章节正文、封面和插图组装为标准 EPUB 文件，供下载完成后打包发送。"""

from __future__ import annotations

from html import escape
from pathlib import Path

from bs4 import BeautifulSoup
from ebooklib import epub

from .models import BookMetadata


class EpubExporter:
    """将缓存章节和媒体资源导出为 EPUB 文件。"""

    @staticmethod
    def _clean_chapter_html(html: str) -> str:
        """清理章节 HTML，移除不适合 EPUB 的标签和属性。"""
        if not html:
            return ""
        soup = BeautifulSoup(html, "lxml")

        for bad in soup.select("script, style, iframe, object, embed"):
            bad.decompose()

        root = soup.select_one(".forum-content") or soup.body or soup
        content = root.decode_contents() if hasattr(root, "decode_contents") else str(root)

        # EPUB/XHTML 中 img 最好有 alt，避免部分阅读器校验报错。
        cleaned = BeautifulSoup(content, "lxml")
        for img in cleaned.select("img"):
            if not img.get("alt"):
                img["alt"] = "illustration"
            # 避免外链 srcset 干扰 EPUB 阅读器。
            for attr in ("srcset", "data-src", "data-original", "data-lazy-src"):
                if img.has_attr(attr):
                    del img[attr]

        body = cleaned.body
        return body.decode_contents() if body else str(cleaned)

    @staticmethod
    def _media_type_from_path(path: Path) -> str:
        """根据文件扩展名推断资源媒体类型。"""
        suffix = path.suffix.lower()
        if suffix in {".jpg", ".jpeg"}:
            return "image/jpeg"
        if suffix == ".png":
            return "image/png"
        if suffix == ".gif":
            return "image/gif"
        if suffix == ".webp":
            return "image/webp"
        if suffix == ".svg":
            return "image/svg+xml"
        if suffix == ".avif":
            return "image/avif"
        return "application/octet-stream"

    def export(
        self,
        book_dir: Path,
        metadata: BookMetadata,
        chapters: list[dict],
        cover_path: Path | None = None,
        image_items: list[dict] | None = None,
    ) -> Path:
        """将章节缓存导出为目标文件。"""
        output = book_dir / "outputs" / f"{metadata.safe_title}.epub"
        output.parent.mkdir(parents=True, exist_ok=True)

        book = epub.EpubBook()
        book.set_identifier(f"esjzone-{metadata.book_id}")
        book.set_title(metadata.title)
        book.set_language("zh-CN")
        book.add_author(metadata.author or "未知作者")

        if cover_path and cover_path.exists():
            book.set_cover(cover_path.name, cover_path.read_bytes())

        for item in image_items or []:
            path = Path(item.get("path", ""))
            href = item.get("epub_href", "")
            if not path.exists() or not href:
                continue
            book.add_item(
                epub.EpubImage(
                    uid=f"img_{len(book.items)}",
                    file_name=href,
                    media_type=item.get("media_type") or self._media_type_from_path(path),
                    content=path.read_bytes(),
                )
            )

        intro = epub.EpubHtml(title="简介", file_name="intro.xhtml", lang="zh-CN")
        intro.content = (
            f"<h1>{escape(metadata.title)}</h1>"
            f"<p>作者：{escape(metadata.author)}</p>"
            f"<p>来源：{escape(metadata.detail_url)}</p>"
            f"<p>{escape(metadata.intro_text)}</p>"
        )
        book.add_item(intro)

        epub_chapters = []
        for idx, chapter in enumerate(chapters, start=1):
            title = chapter.get("title") or f"第 {idx} 章"
            html = chapter.get("processed_html") or chapter.get("html") or ""
            body_html = self._clean_chapter_html(html)
            if not body_html:
                body_html = escape(chapter.get("text") or "").replace("\n", "<br/>")

            item = epub.EpubHtml(title=title, file_name=f"chap_{idx:04d}.xhtml", lang="zh-CN")
            item.content = f"<h2>{escape(title)}</h2>{body_html}"
            book.add_item(item)
            epub_chapters.append(item)

        book.toc = [intro, *epub_chapters]
        book.spine = ["nav", intro, *epub_chapters]
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        epub.write_epub(str(output), book)
        return output
