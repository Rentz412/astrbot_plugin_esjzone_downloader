from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from .client import EsjHttpClient
from .models import AuthContext
from .utils import validate_esj_url


class ImageService:
    def __init__(self, client: EsjHttpClient) -> None:
        self.client = client

    async def download_cover(
        self,
        cover_url: str | None,
        output_path: Path,
        auth: AuthContext,
        referer: str,
    ) -> Path | None:
        if not cover_url:
            return None
        try:
            validate_esj_url(cover_url)
            content, content_type = await self.client.fetch_bytes(cover_url, auth=auth, referer=referer)
            if not content_type.lower().startswith("image/"):
                return None
            suffix = self._suffix_from_content_type(content_type) or Path(urlparse(cover_url).path).suffix or ".jpg"
            target = output_path.with_suffix(suffix)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            return target
        except Exception:
            return None

    def _suffix_from_content_type(self, content_type: str) -> str:
        content_type = content_type.lower().split(";")[0].strip()
        return {
            "image/jpeg": ".jpg",
            "image/jpg": ".jpg",
            "image/png": ".png",
            "image/gif": ".gif",
            "image/webp": ".webp",
        }.get(content_type, "")
