"""ESJZone 登录态管理服务。

封装账号密码登录、Cookie 校验/刷新、用户登录态加密落盘以及认证调试信息输出，避免入口命令层直接处理敏感凭据。"""

from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup
from cryptography.fernet import Fernet

from .models import AuthContext, AuthResult, CookieValidationResult

BASE_URL = "https://www.esjzone.one"
LOGIN_PAGE_URL = f"{BASE_URL}/login"
AUTH_TOKEN_URL = f"{BASE_URL}/my/login"
PASSWORD_LOGIN_URL = f"{BASE_URL}/inc/mem_login.php"
PROFILE_URL = f"{BASE_URL}/my/profile.html"

ALLOWED_COOKIE_DOMAINS = {
    "www.esjzone.one",
    ".esjzone.one",
    "esjzone.one",
    "www.esjzone.cc",
    ".esjzone.cc",
    "esjzone.cc",
}


class EsjAuthService:
    """管理 ESJZone 账号登录、Cookie 校验和本地加密凭据。"""
    def __init__(self, data_dir: Path, config: Any, logger: Any = None):
        """初始化对象依赖和运行时目录。"""
        self.data_dir = data_dir
        self.auth_dir = data_dir / "auth"
        self.users_dir = self.auth_dir / "users"
        self.secret_path = self.auth_dir / "secret.key"
        self.config = config
        self.logger = logger
        self.users_dir.mkdir(parents=True, exist_ok=True)
        self.fernet = Fernet(self._load_or_create_key())

    def _load_or_create_key(self) -> bytes:
        """读取或创建 Fernet 密钥，用于加密本地敏感信息。"""
        self.auth_dir.mkdir(parents=True, exist_ok=True)
        if self.secret_path.exists():
            return self.secret_path.read_bytes()
        key = Fernet.generate_key()
        self.secret_path.write_bytes(key)
        return key

    def _encrypt(self, value: str) -> str:
        """加密需要落盘保存的敏感字符串。"""
        return self.fernet.encrypt(value.encode("utf-8")).decode("utf-8")

    def _decrypt(self, value: str) -> str:
        """解密本地保存的敏感字符串。"""
        return self.fernet.decrypt(value.encode("utf-8")).decode("utf-8")

    @staticmethod
    def mask_email(email: str) -> str:
        """对邮箱进行脱敏展示，避免日志或回复泄露账号。"""
        if "@" not in email:
            return email[:2] + "***"
        name, domain = email.split("@", 1)
        return f"{name[:2]}***@{domain}"

    @staticmethod
    def user_hash_from_event(event) -> tuple[str, str, str]:
        """根据平台和发送者生成稳定的匿名用户标识。"""
        platform_id = ""
        sender_id = ""
        for attr in ("get_platform_id", "get_platform_name"):
            try:
                platform_id = getattr(event, attr)() or platform_id
            except Exception:
                pass
        try:
            sender_id = event.get_sender_id()
        except Exception:
            sender_id = "unknown"
        raw = f"{platform_id}:{sender_id}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest(), platform_id, sender_id

    def _user_file(self, user_hash: str) -> Path:
        """返回指定用户登录态文件路径。"""
        return self.users_dir / f"{user_hash}.json"

    def _debug_cfg(self) -> dict[str, Any]:
        """读取调试配置。"""
        cfg = self.config.get("debug", {}) if hasattr(self.config, "get") else {}
        return cfg if isinstance(cfg, dict) else {}

    def _debug_enabled(self) -> bool:
        """判断调试输出是否启用。"""
        return bool(self._debug_cfg().get("enabled", False))

    def _debug_dir(self) -> Path:
        """创建并返回调试文件目录。"""
        path = self.data_dir / "debug" / "auth"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _debug_log(self, message: str) -> None:
        """按配置输出调试日志。"""
        if self._debug_enabled() and self.logger:
            self.logger.info(f"[esj.debug][auth] {message}")

    def _debug_write_text(self, filename: str, text: str) -> None:
        """按配置保存调试文本。"""
        cfg = self._debug_cfg()
        if not cfg.get("enabled", False) or not cfg.get("save_auth_pages", True):
            return
        (self._debug_dir() / filename).write_text(text, encoding="utf-8", errors="replace")

    def _debug_write_json(self, filename: str, payload: dict[str, Any]) -> None:
        """按配置保存结构化调试信息。"""
        cfg = self._debug_cfg()
        if not cfg.get("enabled", False):
            return
        (self._debug_dir() / filename).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _mask(value: str) -> str:
        """对 Cookie、Token 等敏感片段进行脱敏。"""
        if not value:
            return ""
        return f"{value[:10]}...{value[-6:]}" if len(value) > 20 else "***"

    def _cookie_summary_from_rows(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        """汇总 Cookie 条目，便于调试时确认关键字段是否存在。"""
        keys = {"ews_key", "ews_token", "ws_last", "ws_last_visit_code", "ws_last_visit_post"}
        return {
            "count": len(rows),
            "keys": {
                row.get("name", ""): self._mask(str(row.get("value", "")))
                for row in rows
                if row.get("name") in keys
            },
        }

    @staticmethod
    def _cookie_header_from_rows(rows: list[dict[str, Any]]) -> str:
        """将 Cookie 条目拼接为 HTTP Cookie 请求头。"""
        parts: list[str] = []
        for row in rows:
            name = str((row or {}).get("name", "")).strip()
            value = str((row or {}).get("value", "")).strip()
            if name and value:
                parts.append(f"{name}={value}")
        return "; ".join(parts)

    @staticmethod
    def _cookie_header_from_client(client: httpx.AsyncClient) -> str:
        """从 httpx 客户端 CookieJar 构造 Cookie 请求头。"""
        parts = []
        for cookie in client.cookies.jar:
            # 这里不能过滤得太死。ESJZone 有时会下发 host-only cookie，
            # 裸 requests 脚本会完整保留并发送；插件也应尽量完整保存同站 cookie。
            domain = (cookie.domain or "").lstrip(".")
            if domain and not (domain == "esjzone.one" or domain.endswith(".esjzone.one") or domain == "esjzone.cc" or domain.endswith(".esjzone.cc")):
                continue
            if not cookie.name or not cookie.value:
                continue
            parts.append(f"{cookie.name}={cookie.value}")
        return "; ".join(parts)

    @staticmethod
    def _cookie_jar_dump(client: httpx.AsyncClient) -> list[dict[str, Any]]:
        """将客户端 CookieJar 转为可序列化结构用于保存或调试。"""
        rows: list[dict[str, Any]] = []
        now = time.time()
        for cookie in client.cookies.jar:
            if cookie.domain not in ALLOWED_COOKIE_DOMAINS:
                continue
            if cookie.expires and cookie.expires < now:
                continue
            rows.append({
                "name": cookie.name,
                "value": cookie.value,
                "domain": cookie.domain,
                "path": cookie.path or "/",
                "expires": cookie.expires,
                "secure": cookie.secure,
            })
        return rows

    async def fetch_login_authorization_token(self, client: httpx.AsyncClient) -> str:
        """从登录页提取站点要求的 authorization token。"""
        response = await client.post(
            AUTH_TOKEN_URL,
            data={"plxf": "getAuthToken"},
            headers={
                "Accept": "text/javascript, text/html, application/xml, text/xml, */*",
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "X-Requested-With": "XMLHttpRequest",
                "Origin": BASE_URL,
                "Referer": AUTH_TOKEN_URL,
            },
        )
        response.raise_for_status()
        match = re.search(r"<JinJing>(.*?)</JinJing>", response.text, flags=re.DOTALL)
        if not match:
            raise RuntimeError("未能从 getAuthToken 响应中提取 JinJing token")
        return match.group(1).strip()

    async def login(self, email: str, password: str) -> AuthResult:
        """执行账号密码登录并返回 Cookie 与用户名。"""
        headers = {
            "User-Agent": self.config.get("download", {}).get("user_agent", "Mozilla/5.0"),
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        async with httpx.AsyncClient(headers=headers, timeout=20, follow_redirects=True) as client:
            client.cookies.clear()
            self._debug_log(f"login start email={self.mask_email(email)}")
            page = await client.get(LOGIN_PAGE_URL, headers={"Referer": BASE_URL + "/"})
            page.raise_for_status()
            self._debug_write_text("login_page.html", page.text)
            self._debug_log(f"login page status={page.status_code} final_url={page.url} len={len(page.text)}")

            token = await self.fetch_login_authorization_token(client)
            self._debug_log(f"auth token fetched len={len(token)}")

            response = await client.post(
                PASSWORD_LOGIN_URL,
                data={"email": email, "pwd": password, "remember_me": "on"},
                headers={
                    "Accept": "*/*",
                    "Authorization": token,
                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                    "X-Requested-With": "XMLHttpRequest",
                    "Origin": BASE_URL,
                    "Referer": AUTH_TOKEN_URL,
                },
            )
            response.raise_for_status()
            self._debug_write_text("mem_login_response.txt", response.text)
            self._debug_log(f"mem_login status={response.status_code} final_url={response.url} len={len(response.text)}")

            try:
                payload = response.json()
            except json.JSONDecodeError:
                payload = {}
            redirect_url = payload.get("url") if isinstance(payload, dict) else None
            if redirect_url:
                redirect_url = str(redirect_url).replace("\\/", "/")
                redirect_url = urljoin(BASE_URL, redirect_url)
                redirect_response = await client.get(redirect_url, headers={"Referer": LOGIN_PAGE_URL})
                self._debug_write_text("login_redirect.html", redirect_response.text)
                self._debug_log(f"login redirect final_url={redirect_response.url} status={redirect_response.status_code} len={len(redirect_response.text)}")

            validation = await self.validate_client_cookie(client)
            cookie_rows = self._cookie_jar_dump(client)
            self._debug_write_json(
                "login_result.json",
                {
                    "success": validation.valid,
                    "username": validation.username,
                    "reason": validation.reason,
                    "cookie_header_length": len(self._cookie_header_from_client(client)),
                    "cookie_summary": self._cookie_summary_from_rows(cookie_rows),
                },
            )
            if not validation.valid:
                return AuthResult(False, reason=validation.reason or "登录后个人资料页校验失败")

            if self.logger:
                self.logger.info(
                    f"[esj.auth] login ok username={validation.username or '-'} "
                    f"cookie_jar={len(self._cookie_jar_dump(client))} "
                    f"cookie_header_len={len(self._cookie_header_from_client(client))}"
                )

            return AuthResult(
                success=True,
                username=validation.username,
                cookie_header=self._cookie_header_from_client(client),
                cookie_jar=self._cookie_jar_dump(client),
            )

    async def validate_cookie(self, cookie: str) -> CookieValidationResult:
        """用个人资料页校验 Cookie 是否仍然有效。"""
        headers = {"User-Agent": self.config.get("download", {}).get("user_agent", "Mozilla/5.0")}
        cookies = httpx.Cookies()
        for part in (cookie or "").split(";"):
            name, sep, value = part.strip().partition("=")
            if sep and name and value:
                cookies.set(name.strip(), value.strip(), domain=".esjzone.one", path="/")

        async with httpx.AsyncClient(
            headers=headers,
            cookies=cookies if len(cookies) > 0 else None,
            timeout=20,
            follow_redirects=True,
        ) as client:
            return await self.validate_client_cookie(client)

    async def validate_client_cookie(self, client: httpx.AsyncClient) -> CookieValidationResult:
        """校验指定客户端中已有 Cookie 的有效性。"""
        try:
            response = await client.get(PROFILE_URL, headers={"Referer": BASE_URL + "/"})
            response.raise_for_status()
        except httpx.HTTPError as exc:
            return CookieValidationResult(False, unknown=True, reason=f"网络错误: {type(exc).__name__}")

        html = response.text
        self._debug_write_text("profile_validate.html", html)
        self._debug_log(f"profile validate status={response.status_code} final_url={response.url} len={len(html)}")

        if "window.location.href='/my/login';" in html or 'window.location.href="/my/login";' in html:
            self._debug_write_json(
                "profile_validate.json",
                {
                    "valid": False,
                    "reason": "Cookie 已失效",
                    "final_url": str(response.url),
                    "html_length": len(html),
                    "contains_login_redirect": True,
                    "cookie_summary": self._cookie_summary_from_rows(self._cookie_jar_dump(client)),
                },
            )
            return CookieValidationResult(False, reason="Cookie 已失效")

        soup = BeautifulSoup(html, "lxml")
        username_node = soup.select_one("h6.user-name")
        if username_node:
            username = username_node.get_text(" ", strip=True)
            self._debug_write_json(
                "profile_validate.json",
                {
                    "valid": True,
                    "username": username,
                    "final_url": str(response.url),
                    "html_length": len(html),
                    "cookie_summary": self._cookie_summary_from_rows(self._cookie_jar_dump(client)),
                },
            )
            return CookieValidationResult(True, username=username)

        self._debug_write_json(
            "profile_validate.json",
            {
                "valid": False,
                "reason": "无法识别个人资料页登录态",
                "final_url": str(response.url),
                "html_length": len(html),
                "contains_user_name": False,
                "contains_login_markers": any(marker in html for marker in ("登录", "登入", "/my/login", "/login")),
                "cookie_summary": self._cookie_summary_from_rows(self._cookie_jar_dump(client)),
            },
        )
        return CookieValidationResult(False, reason="无法识别个人资料页登录态")

    async def save_user_auth(self, event, email: str, password: str, result: AuthResult) -> None:
        """加密保存用户账号、密码和 Cookie。"""
        user_hash, platform_id, _sender_id = self.user_hash_from_event(event)
        cookie_from_jar = self._cookie_header_from_rows(result.cookie_jar)
        cookie_header = cookie_from_jar if len(cookie_from_jar) > len(result.cookie_header or "") else result.cookie_header
        payload = {
            "version": 1,
            "platform_id": platform_id,
            "user_id_hash": user_hash,
            "email_encrypted": self._encrypt(email),
            "password_encrypted": self._encrypt(password),
            "cookie_header_encrypted": self._encrypt(cookie_header),
            "cookie_jar_encrypted": self._encrypt(json.dumps(result.cookie_jar, ensure_ascii=False)),
            "cookie_updated_at": int(time.time()),
            "last_login_at": int(time.time()),
            "last_check_at": int(time.time()),
            "status": "valid",
            "username_masked": result.username or self.mask_email(email),
        }
        self._debug_write_json(
            "save_user_auth.json",
            {
                "user_hash_prefix": user_hash[:12],
                "cookie_header_length": len(cookie_header),
                "raw_result_cookie_header_length": len(result.cookie_header or ""),
                "cookie_from_jar_length": len(cookie_from_jar),
                "cookie_summary": self._cookie_summary_from_rows(result.cookie_jar),
            },
        )
        self._user_file(user_hash).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    async def refresh_cookie(self, user_hash: str) -> AuthResult:
        """使用保存的账号密码刷新指定用户 Cookie。"""
        path = self._user_file(user_hash)
        if not path.exists():
            return AuthResult(False, reason="未找到用户认证文件")
        payload = json.loads(path.read_text(encoding="utf-8"))
        email = self._decrypt(payload["email_encrypted"])
        password = self._decrypt(payload["password_encrypted"])
        result = await self.login(email, password)
        if result.success:
            payload["cookie_header_encrypted"] = self._encrypt(result.cookie_header)
            payload["cookie_jar_encrypted"] = self._encrypt(json.dumps(result.cookie_jar, ensure_ascii=False))
            payload["cookie_updated_at"] = int(time.time())
            payload["last_login_at"] = int(time.time())
            payload["status"] = "valid"
            payload["username_masked"] = result.username or self.mask_email(email)
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return result

    async def get_auth_context(self, event) -> AuthContext | None:
        """获取当前事件对应用户的认证上下文，必要时自动刷新。"""
        user_hash, platform_id, sender_id = self.user_hash_from_event(event)
        path = self._user_file(user_hash)
        if not path.exists():
            return None

        payload = json.loads(path.read_text(encoding="utf-8"))
        cookie = self._decrypt(payload.get("cookie_header_encrypted", ""))
        cookie_jar: list[dict[str, Any]] = []
        encrypted_cookie_jar = payload.get("cookie_jar_encrypted", "")
        if encrypted_cookie_jar:
            try:
                cookie_jar = json.loads(self._decrypt(encrypted_cookie_jar))
            except Exception:
                cookie_jar = []

        cookie_from_jar = self._cookie_header_from_rows(cookie_jar)
        if len(cookie_from_jar) > len(cookie):
            self._debug_log(
                f"use cookie header rebuilt from jar old_len={len(cookie)} jar_len={len(cookie_from_jar)}"
            )
            cookie = cookie_from_jar

        self._debug_log(
            f"auth context loaded user_hash={user_hash[:12]} cookie_header_len={len(cookie)} cookie_jar={len(cookie_jar)}"
        )
        self._debug_write_json(
            "auth_context_loaded.json",
            {
                "user_hash_prefix": user_hash[:12],
                "cookie_header_length": len(cookie),
                "cookie_from_jar_length": len(cookie_from_jar),
                "cookie_jar_count": len(cookie_jar),
                "cookie_summary": self._cookie_summary_from_rows(cookie_jar),
            },
        )
        validation = await self.validate_cookie(cookie)
        payload["last_check_at"] = int(time.time())

        if validation.valid:
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            return AuthContext(
                user_hash=user_hash,
                platform_id=platform_id,
                sender_id=sender_id,
                cookie=cookie,
                cookie_jar=cookie_jar,
                username=validation.username,
                email_masked=payload.get("username_masked"),
            )

        if validation.unknown:
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            return None

        refresh = await self.refresh_cookie(user_hash)
        if not refresh.success:
            payload["status"] = "invalid"
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            return None

        return AuthContext(
            user_hash=user_hash,
            platform_id=platform_id,
            sender_id=sender_id,
            cookie=refresh.cookie_header,
            cookie_jar=refresh.cookie_jar,
            username=refresh.username,
            refreshed=True,
        )

    async def require_auth_or_reply(self, event) -> AuthContext | None:
        """命令执行前读取认证上下文；未登录时返回 None。"""
        auth = await self.get_auth_context(event)
        if auth:
            return auth
        return None

    async def logout_user(self, event) -> bool:
        """删除当前事件对应用户的登录态。"""
        user_hash, _, _ = self.user_hash_from_event(event)
        path = self._user_file(user_hash)
        if path.exists():
            path.unlink()
            return True
        return False

    async def logout_all(self) -> int:
        """清空所有已保存的用户登录态。"""
        count = 0
        for path in self.users_dir.glob("*.json"):
            path.unlink()
            count += 1
        return count
