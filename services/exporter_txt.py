from __future__ import annotations

from pathlib import Path

from .models import BookMetadata


class TxtExporter:
    def export(self, book_dir: Path, metadata: BookMetadata, chapters: list[dict]) -> Path:
        output = book_dir / "outputs" / f"{metadata.safe_title}.txt"
        lines = [
            metadata.title,
            f"作者：{metadata.author}",
            f"来源：{metadata.detail_url}",
            "",
            "简介：",
            metadata.intro_text or "无",
            "",
            "目录：",
        ]
        for idx, chapter in enumerate(chapters, start=1):
            lines.append(f"{idx}. {chapter.get('title', '')}")
        lines.append("\n正文：\n")
        for idx, chapter in enumerate(chapters, start=1):
            lines.append(f"\n\n## {idx}. {chapter.get('title', '')}\n")
            lines.append(chapter.get("text", ""))
        output.write_text("\n".join(lines), encoding="utf-8")
        return output
