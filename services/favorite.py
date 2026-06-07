"""ESJZone 个人收藏列表服务。

负责抓取 /my/favorite 多页收藏列表、解析收藏条目，并按用户隔离缓存抓取结果。"""

from __future__ import annotations

import json
import re
import shutil
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .client import EsjHttpClient
from .models import AuthContext, FavoriteBook, FavoriteListResult

BASE_URLS = ("https://www.esjzone.one", "https://www.esjzone.cc")
DETAIL_RE = re.compile(r"/detail/(\d+)(?:\.html)?/?")
BOOT_PAG_TOTAL_RE = re.compile(r"bootpag\s*\(\s*\{.*?total\s*:\s*(\d+)", re.IGNORECASE | re.DOTALL)
FAVORITE_PAGE_RE = re.compile(r"/my/favorite/(\d+)")


class FavoriteRefreshCooldown(Exception):
    """手动刷新冷却尚未结束。"""

    def __init__(self, remaining_seconds: int):
        super().__init__(f"手动刷新过于频繁，请 {remaining_seconds} 秒后再试。")
        self.remaining_seconds = remaining_seconds


class FavoriteService:
    """管理个人收藏列表抓取、解析、缓存和刷新策略。"""

    def __init__(self, data_dir: Path, config: Mapping, logger: Any = None):
        """初始化收藏服务。"""
        self.data_dir = data_dir
        self.config = config
        self.logger = logger
        self.client_factory = EsjHttpClient(config)
        self.users_dir = data_dir / "users"
        self.users_dir.mkdir(parents=True, exist_ok=True)

    def _cfg(self) -> dict[str, Any]:
        """读取收藏配置并兼容异常配置类型。"""
        cfg = self.config.get("favorite", {}) if hasattr(self.config, "get") else {}
        return cfg if isinstance(cfg, dict) else {}

    def passive_ttl(self) -> int:
        """返回被动刷新 TTL。"""
        return max(0, int(self._cfg().get("passive_refresh_ttl_seconds", 600) or 600))

    def manual_cd(self) -> int:
        """返回手动刷新 CD。"""
        return max(0, int(self._cfg().get("manual_refresh_cd_seconds", 60) or 60))

    def max_pages(self) -> int:
        """返回最多抓取页数。"""
        return max(1, int(self._cfg().get("max_pages", 50) or 50))

    def save_raw_html(self) -> bool:
        """是否保存收藏页 HTML。"""
        return bool(self._cfg().get("save_raw_html", False))

    @staticmethod
    def format_time(timestamp: int | float | None = None) -> str:
        """格式化本地时间。"""
        ts = int(timestamp or time.time())
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")

    def favorites_dir(self, auth: AuthContext) -> Path:
        """返回当前用户收藏缓存目录。"""
        path = self.users_dir / auth.user_hash / "favorites"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def cache_path(self, auth: AuthContext) -> Path:
        """返回当前用户收藏缓存文件路径。"""
        return self.favorites_dir(auth) / "cache.json"

    def pages_dir(self, auth: AuthContext) -> Path:
        """返回当前用户收藏页 HTML 调试目录。"""
        path = self.favorites_dir(auth) / "pages"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def load_cache_payload(self, auth: AuthContext) -> dict[str, Any] | None:
        """读取当前用户收藏缓存 JSON。"""
        path = self.cache_path(auth)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            if self.logger:
                self.logger.warning("收藏列表缓存读取失败", exc_info=True)
            return None
        return payload if isinstance(payload, dict) else None

    def _has_valid_cache(self, payload: dict[str, Any] | None) -> bool:
        """判断缓存是否包含有效抓取结果。"""
        if not payload:
            return False
        return int(payload.get("fetched_at") or 0) > 0 and isinstance(payload.get("items"), list)

    def _payload_to_result(
        self,
        payload: dict[str, Any],
        *,
        from_cache: bool,
        status_message: str = "",
        error_message: str = "",
    ) -> FavoriteListResult:
        """将缓存 JSON 转为结果对象。"""
        items = []
        for row in payload.get("items", []):
            if not isinstance(row, dict):
                continue
            items.append(
                FavoriteBook(
                    index=int(row.get("index") or len(items) + 1),
                    book_id=str(row.get("book_id") or ""),
                    title=str(row.get("title") or ""),
                    url=str(row.get("url") or ""),
                    latest=str(row.get("latest") or ""),
                    latest_url=str(row.get("latest_url") or ""),
                    last_read=str(row.get("last_read") or ""),
                    updated_at=str(row.get("updated_at") or ""),
                )
            )
        return FavoriteListResult(
            user_hash=str(payload.get("user_hash") or ""),
            username=str(payload.get("username") or "当前用户"),
            source_host=str(payload.get("source_host") or "www.esjzone.one"),
            source_url=str(payload.get("source_url") or "https://www.esjzone.one/my/favorite"),
            fetched_at=int(payload.get("fetched_at") or 0),
            fetched_at_text=str(payload.get("fetched_at_text") or ""),
            items=items,
            total_site_pages=int(payload.get("total_site_pages") or 1),
            fetched_pages=int(payload.get("fetched_pages") or 1),
            from_cache=from_cache,
            status_message=status_message,
            error_message=error_message,
        )

    def _result_to_payload(
        self,
        auth: AuthContext,
        result: FavoriteListResult,
        *,
        old_payload: dict[str, Any] | None = None,
        manual_refresh: bool = False,
    ) -> dict[str, Any]:
        """将结果对象转为缓存 JSON。"""
        old_payload = old_payload or {}
        now = int(time.time())
        payload = {
            "version": 1,
            "user_hash": auth.user_hash,
            "platform_id": auth.platform_id,
            "sender_id": auth.sender_id,
            "username": result.username,
            "source_host": result.source_host,
            "source_url": result.source_url,
            "total_site_pages": result.total_site_pages,
            "fetched_pages": result.fetched_pages,
            "fetched_at": result.fetched_at,
            "fetched_at_text": result.fetched_at_text,
            "manual_refresh_at": int(old_payload.get("manual_refresh_at") or 0),
            "manual_refresh_at_text": str(old_payload.get("manual_refresh_at_text") or ""),
            "manual_refresh_attempt_at": int(old_payload.get("manual_refresh_attempt_at") or 0),
            "manual_refresh_attempt_at_text": str(old_payload.get("manual_refresh_attempt_at_text") or ""),
            "passive_refresh_ttl_seconds": self.passive_ttl(),
            "manual_refresh_cd_seconds": self.manual_cd(),
            "count": len(result.items),
            "items": [asdict(item) for item in result.items],
        }
        if manual_refresh:
            payload["manual_refresh_at"] = now
            payload["manual_refresh_at_text"] = self.format_time(now)
        return payload

    def save_result(self, auth: AuthContext, result: FavoriteListResult, *, manual_refresh: bool = False) -> None:
        """保存抓取结果。"""
        old_payload = self.load_cache_payload(auth)
        payload = self._result_to_payload(auth, result, old_payload=old_payload, manual_refresh=manual_refresh)
        self.cache_path(auth).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def mark_manual_attempt(self, auth: AuthContext) -> None:
        """记录一次手动刷新尝试。"""
        payload = self.load_cache_payload(auth) or {
            "version": 1,
            "user_hash": auth.user_hash,
            "platform_id": auth.platform_id,
            "sender_id": auth.sender_id,
            "username": self.username_from_auth(auth),
            "items": [],
            "fetched_at": 0,
        }
        now = int(time.time())
        payload["manual_refresh_attempt_at"] = now
        payload["manual_refresh_attempt_at_text"] = self.format_time(now)
        payload["manual_refresh_cd_seconds"] = self.manual_cd()
        self.cache_path(auth).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def manual_refresh_remaining(self, auth: AuthContext) -> int:
        """返回手动刷新剩余冷却秒数。"""
        payload = self.load_cache_payload(auth) or {}
        last_attempt = int(payload.get("manual_refresh_attempt_at") or 0)
        if last_attempt <= 0:
            return 0
        remaining = self.manual_cd() - (int(time.time()) - last_attempt)
        return max(0, remaining)

    @staticmethod
    def username_from_auth(auth: AuthContext) -> str:
        """从认证上下文提取展示用用户名。"""
        return (auth.username or auth.email_masked or "").strip() or "当前用户"

    @staticmethod
    def _normalize_text(value: str) -> str:
        """压缩空白。"""
        return re.sub(r"\s+", " ", value or "").strip()

    @staticmethod
    def _looks_like_login_page(html: str) -> bool:
        """识别登录失效页面。"""
        markers = (
            "window.location.href='/my/login';",
            'window.location.href="/my/login";',
            "window.location.href='/login';",
            'window.location.href="/login";',
        )
        if any(marker in html for marker in markers):
            return True
        title_match = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
        title = FavoriteService._normalize_text(title_match.group(1)) if title_match else ""
        return bool(title and ("登录" in title or "登入" in title) and "我的收藏" not in title)

    @staticmethod
    def parse_username(html: str) -> str:
        """从收藏页兜底解析用户名。"""
        soup = BeautifulSoup(html, "lxml")
        for selector in (".toolbar-dropdown h6.user-name", ".user-name", ".user-data h4"):
            node = soup.select_one(selector)
            if node:
                text = FavoriteService._normalize_text(node.get_text(" ", strip=True))
                if text:
                    return text
        return ""

    @staticmethod
    def parse_total_pages(html: str) -> int:
        """解析收藏页总页数。"""
        match = BOOT_PAG_TOTAL_RE.search(html or "")
        if match:
            return max(1, int(match.group(1)))
        pages = [int(m.group(1)) for m in FAVORITE_PAGE_RE.finditer(html or "") if m.group(1).isdigit()]
        return max(pages) if pages else 1

    @staticmethod
    def _normalize_esj_url(url: str, base_url: str) -> str:
        """将 ESJZone 链接标准化为当前抓取域名下的绝对链接。"""
        value = (url or "").strip()
        if not value:
            return ""
        abs_url = urljoin(base_url + "/", value)
        parsed = urlparse(abs_url)
        base_host = urlparse(base_url).hostname or "www.esjzone.one"
        if parsed.hostname in {"www.esjzone.one", "www.esjzone.cc"}:
            return f"https://{base_host}{parsed.path}"
        return abs_url

    @staticmethod
    def _strip_label(text: str, label: str) -> str:
        """去除形如 最新： / 更新日期： 的前缀。"""
        value = FavoriteService._normalize_text(text)
        value = re.sub(rf"^{re.escape(label)}\s*[:：]?\s*", "", value)
        return value.strip()

    def parse_items(self, html: str, base_url: str) -> list[FavoriteBook]:
        """解析单页收藏条目。"""
        soup = BeautifulSoup(html, "lxml")
        items: list[FavoriteBook] = []
        for row in soup.select("table.table tbody tr"):
            title_link = row.select_one("h5.product-title a[href]")
            if not title_link:
                continue
            title = self._normalize_text(title_link.get_text(" ", strip=True))
            detail_url = self._normalize_esj_url(title_link.get("href", ""), base_url)
            book_match = DETAIL_RE.search(detail_url)
            if not title or not book_match:
                continue

            latest = ""
            latest_url = ""
            latest_node = row.select_one(".book-ep .mr-3")
            if latest_node:
                latest_link = latest_node.select_one("a[href]")
                if latest_link:
                    latest = self._normalize_text(latest_link.get_text(" ", strip=True))
                    latest_url = self._normalize_esj_url(latest_link.get("href", ""), base_url)
                else:
                    latest = self._strip_label(latest_node.get_text(" ", strip=True), "最新")

            last_read = ""
            for node in row.select(".book-ep div"):
                text = self._normalize_text(node.get_text(" ", strip=True))
                if "最後觀看" in text:
                    last_read = re.sub(r"^.*?最後觀看\s*[:：]\s*", "", text).strip()
                    break

            updated_at = ""
            update_node = row.select_one(".book-update")
            if update_node:
                updated_at = self._strip_label(update_node.get_text(" ", strip=True), "更新日期")

            items.append(
                FavoriteBook(
                    index=0,
                    book_id=book_match.group(1),
                    title=title,
                    url=detail_url,
                    latest=latest,
                    latest_url=latest_url,
                    last_read=last_read,
                    updated_at=updated_at,
                )
            )
        return items

    async def _fetch_from_base(self, auth: AuthContext, base_url: str) -> FavoriteListResult:
        """从指定域名抓取全部收藏页。"""
        first_url = f"{base_url}/my/favorite"
        html_pages: list[str] = []
        async with self.client_factory.build_client(auth) as client:
            first_html = await self.client_factory.get_text(client, first_url, referer=f"{base_url}/")
            if self._looks_like_login_page(first_html):
                raise RuntimeError("ESJZone 登录状态已失效")
            total_pages = min(self.parse_total_pages(first_html), self.max_pages())
            html_pages.append(first_html)

            for page_no in range(2, total_pages + 1):
                page_url = f"{base_url}/my/favorite/{page_no}"
                html = await self.client_factory.get_text(client, page_url, referer=first_url)
                if self._looks_like_login_page(html):
                    raise RuntimeError("ESJZone 登录状态已失效")
                html_pages.append(html)

        if self.save_raw_html():
            pages_dir = self.pages_dir(auth)
            shutil.rmtree(pages_dir, ignore_errors=True)
            pages_dir.mkdir(parents=True, exist_ok=True)
            for idx, html in enumerate(html_pages, start=1):
                (pages_dir / f"page_{idx}.html").write_text(html, encoding="utf-8", errors="replace")

        items: list[FavoriteBook] = []
        seen: set[str] = set()
        for html in html_pages:
            for item in self.parse_items(html, base_url):
                if item.book_id in seen:
                    continue
                seen.add(item.book_id)
                item.index = len(items) + 1
                items.append(item)

        now = int(time.time())
        username = self.username_from_auth(auth) or self.parse_username(html_pages[0]) or "当前用户"
        return FavoriteListResult(
            user_hash=auth.user_hash,
            username=username,
            source_host=urlparse(base_url).hostname or "www.esjzone.one",
            source_url=first_url,
            fetched_at=now,
            fetched_at_text=self.format_time(now),
            items=items,
            total_site_pages=total_pages,
            fetched_pages=len(html_pages),
            from_cache=False,
        )

    async def fetch_all(self, auth: AuthContext) -> FavoriteListResult:
        """依次尝试可用域名并抓取完整收藏列表。"""
        errors: list[str] = []
        for base_url in BASE_URLS:
            try:
                return await self._fetch_from_base(auth, base_url)
            except Exception as exc:
                errors.append(f"{base_url}: {type(exc).__name__}: {exc}")
                if self.logger:
                    self.logger.warning(f"收藏列表抓取失败，将尝试下一个域名：{base_url}", exc_info=True)
        raise RuntimeError("；".join(errors) or "收藏列表抓取失败")

    async def get_favorites(self, auth: AuthContext, *, force_refresh: bool = False) -> FavoriteListResult:
        """根据缓存策略获取收藏列表。"""
        old_payload = self.load_cache_payload(auth)

        if force_refresh:
            remaining = self.manual_refresh_remaining(auth)
            if remaining > 0:
                raise FavoriteRefreshCooldown(remaining)
            self.mark_manual_attempt(auth)
            try:
                result = await self.fetch_all(auth)
                result.status_message = "手动刷新成功"
                self.save_result(auth, result, manual_refresh=True)
                return result
            except Exception as exc:
                if self._has_valid_cache(old_payload):
                    return self._payload_to_result(
                        old_payload,
                        from_cache=True,
                        status_message="手动刷新失败，已展示上次缓存",
                        error_message=f"{type(exc).__name__}: {exc}",
                    )
                raise

        if not self._has_valid_cache(old_payload):
            result = await self.fetch_all(auth)
            result.status_message = "首次获取成功"
            self.save_result(auth, result)
            return result

        fetched_at = int(old_payload.get("fetched_at") or 0)
        if int(time.time()) - fetched_at >= self.passive_ttl():
            try:
                result = await self.fetch_all(auth)
                ttl = self.passive_ttl()
                unit_text = f"{ttl // 60} 分钟" if ttl >= 60 else f"{ttl} 秒"
                result.status_message = f"缓存超过 {unit_text}，已自动刷新"
                self.save_result(auth, result)
                return result
            except Exception as exc:
                return self._payload_to_result(
                    old_payload,
                    from_cache=True,
                    status_message="自动刷新失败，已展示上次缓存",
                    error_message=f"{type(exc).__name__}: {exc}",
                )

        return self._payload_to_result(old_payload, from_cache=True, status_message="使用缓存数据")

    def clear_cache(self, auth: AuthContext) -> bool:
        """清除当前用户收藏缓存。"""
        path = self.favorites_dir(auth)
        existed = path.exists() and any(path.iterdir())
        shutil.rmtree(path, ignore_errors=True)
        path.mkdir(parents=True, exist_ok=True)
        return existed