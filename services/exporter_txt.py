from __future__ import annotations

from pathlib import Path

from .models import BookMetadata, ChapterData


class TxtExporter:
    async def export(self, metadata: BookMetadata, chapters: list[ChapterData], output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        ordered = sorted(chapters, key=lambda item: item.index)

        lines: list[str] = [
            metadata.title,
            f"作者：{metadata.author}",
            f"来源：{metadata.detail_url}",
            "",
            "简介：",
            metadata.intro_text or "无",
            "",
            "目录：",
        ]

        for chapter in ordered:
            lines.append(f"{chapter.index + 1}. {chapter.title}")

        lines.append("\n正文：\n")

        for chapter in ordered:
            lines.append("=" * 40)
            lines.append(chapter.txt_segment)

        output_path.write_text("\n".join(lines), encoding="utf-8")
        return output_path
