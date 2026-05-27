from __future__ import annotations

import asyncio
from collections.abc import Mapping

import httpx

from .models import AuthContext
from .utils import validate_esj_url


class EsjHttpClient:
    def __init__(
        self,
        user_agent: str,
        timeout: int = 15,
        image_timeout: int = 8,
        max_retries: int = 3,
        proxy: str | None = None,
    ) -> None:
        self.user_agent = user_agent
        self.timeout = timeout
        self.image_timeout = image_timeout
        self.max_retries = max_retries
        self.proxy = proxy or None
        self._client: httpx.AsyncClient | None = None

    async def get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            kwargs = {
                "headers": {"User-Agent": self.user_agent},
                "follow_redirects": False,
                "timeout": httpx.Timeout(self.timeout),
            }
            if self.proxy:
                kwargs["proxy"] = self.proxy
            self._client = httpx.AsyncClient(**kwargs)
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    def _headers(self, auth: AuthContext | None = None, extra: Mapping[str, str] | None = None) -> dict[str, str]:
        headers = {"User-Agent": self.user_agent}
        if auth and auth.cookie:
            headers["Cookie"] = auth.cookie
        if extra:
            headers.update(extra)
        return headers

    async def fetch_text(
        self,
        url: str,
        auth: AuthContext | None = None,
        *,
        referer: str | None = None,
        retries: int | None = None,
    ) -> str:
        validate_esj_url(url)
        headers = {}
        if referer:
            headers["Referer"] = referer
        response = await self._request_with_retries(
            "GET",
            url,
            auth=auth,
            headers=headers,
            retries=retries,
        )
        return response.text

    async def fetch_bytes(
        self,
        url: str,
        auth: AuthContext | None = None,
        *,
        referer: str | None = None,
        retries: int | None = None,
    ) -> tuple[bytes, str]:
        validate_esj_url(url)
        headers = {}
        if referer:
            headers["Referer"] = referer
        response = await self._request_with_retries(
            "GET",
            url,
            auth=auth,
            headers=headers,
            retries=retries,
            timeout=self.image_timeout,
        )
        return response.content, response.headers.get("content-type", "")

    async def post_form(
        self,
        url: str,
        data: Mapping[str, str],
        *,
        headers: Mapping[str, str] | None = None,
        retries: int | None = None,
    ) -> httpx.Response:
        validate_esj_url(url)
        return await self._request_with_retries(
            "POST",
            url,
            data=data,
            headers=headers,
            retries=retries,
        )

    async def _request_with_retries(
        self,
        method: str,
        url: str,
        *,
        auth: AuthContext | None = None,
        headers: Mapping[str, str] | None = None,
        data: Mapping[str, str] | None = None,
        retries: int | None = None,
        timeout: int | None = None,
    ) -> httpx.Response:
        attempts = self.max_retries if retries is None else retries
        client = await self.get_client()
        last_error: Exception | None = None

        for attempt in range(attempts + 1):
            try:
                response = await client.request(
                    method,
                    url,
                    data=data,
                    headers=self._headers(auth, headers),
                    timeout=timeout or self.timeout,
                )
                if 300 <= response.status_code < 400 and response.headers.get("location"):
                    location = str(response.headers["location"])
                    redirect_url = str(httpx.URL(url).join(location))
                    validate_esj_url(redirect_url)
                    response = await client.request(
                        method,
                        redirect_url,
                        data=data,
                        headers=self._headers(auth, headers),
                        timeout=timeout or self.timeout,
                    )
                response.raise_for_status()
                return response
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
                if attempt >= attempts:
                    break
                await asyncio.sleep(0.5 * (attempt + 1))

        raise RuntimeError(f"请求失败：{url}") from last_error
