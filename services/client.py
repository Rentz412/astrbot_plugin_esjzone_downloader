"""ESJZone HTTP 客户端工厂。

集中管理请求头、Cookie 注入、URL 合法性校验和 HTTP 错误处理，便于后续适配站点域名或反爬策略变化。"""

from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import urlparse

import httpx

from .models import AuthContext

ALLOWED_ESJ_HOSTS = {"www.esjzone.one", "www.esjzone.cc"}


class EsjHttpClient:
    """创建带统一请求头和认证 Cookie 的 httpx 异步客户端。"""
    def __init__(self, config: Mapping):
        """初始化对象依赖和运行时目录。"""
        download = config.get("download", {}) if isinstance(config, Mapping) else {}
        proxy = config.get("proxy", {}) if isinstance(config, Mapping) else {}
        self.user_agent = download.get("user_agent") or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125 Safari/537.36"
        self.timeout = float(download.get("request_timeout") or 15)
        self.proxy_url = proxy.get("url") if proxy.get("enabled") else None
        self.last_response_info: dict[str, object] = {}

    def build_headers(self, referer: str = "https://www.esjzone.one/") -> dict[str, str]:
        """生成访问 ESJZone 时使用的统一请求头。"""
        return {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Origin": "https://www.esjzone.one",
            "Referer": referer,
        }

    def _build_cookies(self, auth: AuthContext | None) -> httpx.Cookies | None:
        """根据认证上下文构造 httpx Cookie 容器。"""
        if not auth:
            return None
        cookies = httpx.Cookies()
        if auth.cookie_jar:
            for row in auth.cookie_jar:
                name = str((row or {}).get("name", "")).strip()
                value = str((row or {}).get("value", "")).strip()
                if not name or not value:
                    continue
                domain = str((row or {}).get("domain", "")).strip() or ".esjzone.one"
                path = str((row or {}).get("path", "")).strip() or "/"
                cookies.set(name, value, domain=domain, path=path)
        elif auth.cookie:
            for part in auth.cookie.split(";"):
                name, sep, value = part.strip().partition("=")
                if sep and name and value:
                    cookies.set(name.strip(), value.strip(), domain=".esjzone.one", path="/")
        return cookies if len(cookies) > 0 else None

    def build_client(self, auth: AuthContext | None = None) -> httpx.AsyncClient:
        """创建配置好超时、重定向、请求头和 Cookie 的异步客户端。"""
        headers = self.build_headers()
        if auth and auth.cookie:
            # 双保险：
            # 1. CookieJar 负责按 domain/path 模拟浏览器行为；
            # 2. 显式 Cookie Header 避免 httpx 因历史 cookie domain/path 不完全匹配而漏发。
            headers["Cookie"] = auth.cookie
        kwargs = {
            "headers": headers,
            "timeout": self.timeout,
            "follow_redirects": True,
        }
        cookies = self._build_cookies(auth)
        if cookies is not None:
            kwargs["cookies"] = cookies
        if self.proxy_url:
            kwargs["proxy"] = self.proxy_url
        return httpx.AsyncClient(**kwargs)

    @staticmethod
    def validate_esj_url(url: str) -> None:
        """限制请求目标为 ESJZone 允许域名，避免 SSRF 风险。"""
        parsed = urlparse(url)
        if parsed.scheme != "https":
            raise ValueError("只允许 HTTPS")
        if parsed.hostname not in ALLOWED_ESJ_HOSTS:
            raise ValueError("非 ESJZone 白名单域名")
        if parsed.username or parsed.password:
            raise ValueError("URL 不允许包含用户名或密码")

    async def get_text(self, client: httpx.AsyncClient, url: str, referer: str = "https://www.esjzone.one/") -> str:
        """发送 GET 请求并返回文本内容。"""
        self.validate_esj_url(url)
        response = await client.get(url, headers=self.build_headers(referer))
        response.raise_for_status()
        self.validate_esj_url(str(response.url))
        self.last_response_info = {
            "request_url": url,
            "final_url": str(response.url),
            "status_code": response.status_code,
            "content_type": response.headers.get("content-type", ""),
            "text_length": len(response.text),
            "request_cookie_header_present": bool(client.headers.get("Cookie")),
            "request_cookie_header_length": len(client.headers.get("Cookie", "")),
        }
        return response.text

    async def get_bytes(
        self,
        client: httpx.AsyncClient,
        url: str,
        referer: str = "https://www.esjzone.one/",
        allow_external: bool = False,
    ) -> tuple[bytes, str]:
        """发送 GET 请求并返回二进制内容和响应类型。"""
        if allow_external:
            parsed = urlparse(url)
            if parsed.scheme not in {"https", "http"} or parsed.username or parsed.password:
                raise ValueError("图片 URL 非法")
        else:
            self.validate_esj_url(url)
        headers = self.build_headers(referer)
        headers["Accept"] = "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8"
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        if allow_external:
            parsed_final = urlparse(str(response.url))
            if parsed_final.scheme not in {"https", "http"} or parsed_final.username or parsed_final.password:
                raise ValueError("图片最终 URL 非法")
        else:
            self.validate_esj_url(str(response.url))
        content = response.content
        content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        self.last_response_info = {
            "request_url": url,
            "final_url": str(response.url),
            "status_code": response.status_code,
            "content_type": content_type,
            "bytes_length": len(content),
            "request_cookie_header_present": bool(client.headers.get("Cookie")),
            "request_cookie_header_length": len(client.headers.get("Cookie", "")),
        }
        return content, content_type
