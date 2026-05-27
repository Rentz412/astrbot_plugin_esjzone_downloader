from __future__ import annotations

import json
import time
from hashlib import sha256
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup
from cryptography.fernet import Fernet, InvalidToken

from .client import EsjHttpClient
from .models import AuthContext, AuthResult, CookieValidationResult
from .utils import is_allowed_cookie_domain, mask_email


LOGIN_URL = "https://www.esjzone.one/inc/mem_login.php"
PROFILE_URL = "https://www.esjzone.one/my/profile.html"


class EsjAuthService:
    def __init__(self, data_dir: Path, client: EsjHttpClient) -> None:
        self.data_dir = data_dir
        self.client = client
        self.auth_dir = data_dir / "auth"
        self.users_dir = self.auth_dir / "users"
        self.secret_path = self.auth_dir / "secret.key"
        self.users_dir.mkdir(parents=True, exist_ok=True)
        self._fernet = self._load_or_create_fernet()

    def _load_or_create_fernet(self) -> Fernet:
        self.auth_dir.mkdir(parents=True, exist_ok=True)
        if not self.secret_path.exists():
            self.secret_path.write_bytes(Fernet.generate_key())
        return Fernet(self.secret_path.read_bytes())

    def _encrypt(self, text: str) -> str:
        return self._fernet.encrypt(text.encode("utf-8")).decode("utf-8")

    def _decrypt(self, token: str) -> str:
        try:
            return self._fernet.decrypt(token.encode("utf-8")).decode("utf-8")
        except InvalidToken as exc:
            raise ValueError("认证数据无法解密，可能 secret.key 已变化") from exc

    def get_user_hash(self, event: Any) -> tuple[str, str, str]:
        platform_id = ""
        if hasattr(event, "get_platform_id"):
            platform_id = event.get_platform_id() or ""
        if not platform_id and hasattr(event, "get_platform_name"):
            platform_id = event.get_platform_name() or ""
        sender_id = event.get_sender_id()
        user_key = f"{platform_id}:{sender_id}"
        return sha256(user_key.encode("utf-8")).hexdigest(), platform_id, sender_id

    def _user_file(self, user_hash: str) -> Path:
        return self.users_dir / f"{user_hash}.json"

    async def login(self, email: str, password: str) -> AuthResult:
        """登录 ESJZone。

        这里不能只读取登录响应的 `response.cookies`，因为站点可能把 Cookie 写入
        AsyncClient 的 cookie jar，且后续 profile 校验必须沿用同一个会话。
        因此登录阶段使用独立临时 client：POST 登录 -> 同 client GET profile -> 序列化 client.cookies.jar。
        """
        headers = {
            "User-Agent": self.client.user_agent,
            "Accept": "*/*",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": "https://www.esjzone.one",
            "Referer": "https://www.esjzone.one/login",
        }
        client_kwargs: dict[str, Any] = {
            "headers": {"User-Agent": self.client.user_agent, "Accept": "*/*"},
            "follow_redirects": False,
            "timeout": httpx.Timeout(self.client.timeout),
        }
        if self.client.proxy:
            client_kwargs["proxy"] = self.client.proxy

        async with httpx.AsyncClient(**client_kwargs) as login_client:
            response = await login_client.post(
                LOGIN_URL,
                data={"email": email, "pwd": password, "remember_me": "on"},
                headers=headers,
            )
            response.raise_for_status()

            validation = await self.validate_client_cookie(login_client)
            if not validation.valid:
                return AuthResult(False, validation.message or "登录失败：Cookie 校验未通过")

            cookie_jar = self._serialize_cookies(login_client.cookies.jar)
            cookie_header = self._cookie_header(cookie_jar)
            if not cookie_header:
                return AuthResult(False, "登录失败：站点未返回有效 Cookie")

            return AuthResult(
                success=True,
                message="登录成功",
                cookie=cookie_header,
                cookie_jar=cookie_jar,
                username=validation.username,
            )

    async def save_login(self, event: Any, email: str, password: str, result: AuthResult) -> None:
        user_hash, platform_id, _ = self.get_user_hash(event)
        now = int(time.time())
        payload = {
            "version": 1,
            "platform_id": platform_id,
            "user_id_hash": user_hash,
            "email_encrypted": self._encrypt(email),
            "password_encrypted": self._encrypt(password),
            "cookie_header_encrypted": self._encrypt(result.cookie),
            "cookie_jar_encrypted": self._encrypt(json.dumps(result.cookie_jar, ensure_ascii=False)),
            "cookie_updated_at": now,
            "last_login_at": now,
            "last_check_at": now,
            "status": "valid",
            "email_masked": mask_email(email),
            "username_masked": result.username or "",
        }
        path = self._user_file(user_hash)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    async def validate_cookie(self, cookie: str) -> CookieValidationResult:
        try:
            headers = {
                "User-Agent": self.client.user_agent,
                "Accept": "*/*",
                "Cookie": cookie,
            }
            client_kwargs: dict[str, Any] = {
                "headers": headers,
                "follow_redirects": False,
                "timeout": httpx.Timeout(self.client.timeout),
            }
            if self.client.proxy:
                client_kwargs["proxy"] = self.client.proxy
            async with httpx.AsyncClient(**client_kwargs) as validate_client:
                html = await self._fetch_profile_html(validate_client)
        except Exception as exc:
            return CookieValidationResult(False, unknown=True, message=f"网络错误：{type(exc).__name__}")

        return self._parse_profile_validation(html)

    async def validate_client_cookie(self, client: Any) -> CookieValidationResult:
        try:
            html = await self._fetch_profile_html(client)
        except Exception as exc:
            return CookieValidationResult(False, unknown=True, message=f"网络错误：{type(exc).__name__}")
        return self._parse_profile_validation(html)

    async def refresh_cookie(self, user_hash: str) -> AuthResult:
        record = self._load_user_record(user_hash)
        if not record:
            return AuthResult(False, "未找到登录记录")
        email = self._decrypt(record.get("email_encrypted", ""))
        password = self._decrypt(record.get("password_encrypted", ""))
        result = await self.login(email, password)
        if result.success:
            now = int(time.time())
            record["cookie_header_encrypted"] = self._encrypt(result.cookie)
            record["cookie_jar_encrypted"] = self._encrypt(json.dumps(result.cookie_jar, ensure_ascii=False))
            record["cookie_updated_at"] = now
            record["last_login_at"] = now
            record["last_check_at"] = now
            record["status"] = "valid"
            record["username_masked"] = result.username or ""
            self._user_file(user_hash).write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        return result

    async def get_auth_context(self, event: Any) -> AuthContext | None:
        user_hash, platform_id, sender_id = self.get_user_hash(event)
        record = self._load_user_record(user_hash)
        if not record:
            return None

        cookie = self._decrypt(record.get("cookie_header_encrypted", ""))
        validation = await self.validate_cookie(cookie)
        record["last_check_at"] = int(time.time())

        if validation.valid:
            record["status"] = "valid"
            self._user_file(user_hash).write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
            return AuthContext(
                user_hash=user_hash,
                platform_id=platform_id,
                sender_id=sender_id,
                cookie=cookie,
                email_masked=record.get("email_masked"),
                username=validation.username or record.get("username_masked"),
                login_valid=True,
            )

        if validation.unknown:
            self._user_file(user_hash).write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
            return AuthContext(
                user_hash=user_hash,
                platform_id=platform_id,
                sender_id=sender_id,
                cookie=cookie,
                email_masked=record.get("email_masked"),
                username=record.get("username_masked"),
                login_valid=True,
            )

        refreshed = await self.refresh_cookie(user_hash)
        if not refreshed.success:
            record["status"] = "invalid"
            self._user_file(user_hash).write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
            return None

        return AuthContext(
            user_hash=user_hash,
            platform_id=platform_id,
            sender_id=sender_id,
            cookie=refreshed.cookie,
            email_masked=record.get("email_masked"),
            username=refreshed.username,
            login_valid=True,
            refreshed=True,
        )

    async def require_auth_or_reply(self, event: Any) -> AuthContext | None:
        auth = await self.get_auth_context(event)
        if auth:
            return auth
        group_id = ""
        if hasattr(event, "get_group_id"):
            group_id = event.get_group_id() or ""
        if group_id:
            yield_text = "你尚未登录 ESJZone。请私聊机器人执行 /esj l <邮箱> <密码> 后再使用该命令。"
        else:
            yield_text = "你尚未登录 ESJZone，无法执行该命令。\n\n请发送：/esj l <邮箱> <密码>"
        await event.send(event.plain_result(yield_text))
        return None

    async def logout_user(self, event: Any) -> bool:
        user_hash, _, _ = self.get_user_hash(event)
        path = self._user_file(user_hash)
        if path.exists():
            path.unlink()
            return True
        return False

    async def logout_all(self) -> int:
        count = 0
        for path in self.users_dir.glob("*.json"):
            path.unlink()
            count += 1
        return count

    async def _fetch_profile_html(self, client: httpx.AsyncClient) -> str:
        response = await client.get(PROFILE_URL)
        if response.is_redirect:
            location = response.headers.get("location", "")
            if "/my/login" in location or "/login" in location:
                return "window.location.href='/my/login';"
        response.raise_for_status()
        return response.text

    def _parse_profile_validation(self, html: str) -> CookieValidationResult:
        if "window.location.href='/my/login';" in html or 'window.location.href="/my/login";' in html:
            return CookieValidationResult(False, message="Cookie 已失效")

        soup = BeautifulSoup(html, "lxml")
        username_node = soup.select_one("h6.user-name")
        if username_node:
            return CookieValidationResult(True, username=username_node.get_text(" ", strip=True), message="Cookie 有效")

        # 兼容站点轻微结构变化：profile 页没有跳登录，且包含用户资料区域时，不要直接判定失效。
        profile_markers = ("/my/logout", "會員", "会员", "profile", "user-name")
        if any(marker in html for marker in profile_markers):
            return CookieValidationResult(True, username=None, message="Cookie 有效")

        return CookieValidationResult(False, unknown=True, message="无法识别登录状态")

    def _load_user_record(self, user_hash: str) -> dict[str, Any] | None:
        path = self._user_file(user_hash)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def _serialize_cookies(self, jar: Any) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for cookie in jar:
            domain = getattr(cookie, "domain", "") or "www.esjzone.one"
            name = getattr(cookie, "name", "")
            value = getattr(cookie, "value", "")
            path = getattr(cookie, "path", "/") or "/"
            expires = getattr(cookie, "expires", None)
            if not name or not value:
                continue
            if not is_allowed_cookie_domain(domain):
                continue
            if not path.startswith("/"):
                continue
            if expires and int(expires) < int(time.time()):
                continue
            items.append(
                {
                    "name": name,
                    "value": value,
                    "domain": domain,
                    "path": path,
                    "expires": expires,
                    "secure": bool(getattr(cookie, "secure", False)),
                    "httponly": "httponly" in getattr(cookie, "_rest", {}),
                }
            )
        return items

    def _cookie_header(self, cookie_jar: list[dict[str, Any]]) -> str:
        return "; ".join(f"{item['name']}={item['value']}" for item in cookie_jar if item.get("name") and item.get("value"))
