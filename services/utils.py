from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from urllib.parse import urlparse


PLUGIN_NAME = "astrbot_plugin_esjzone_downloader"

ALLOWED_ESJ_HOSTS = {"www.esjzone.one", "www.esjzone.cc"}
ALLOWED_COOKIE_DOMAINS = {
    "www.esjzone.one",
    ".esjzone.one",
    "esjzone.one",
    "www.esjzone.cc",
    ".esjzone.cc",
    "esjzone.cc",
}

WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


class EsjSecurityError(ValueError):
    """Raised when user supplied URL or path violates security rules."""


def safe_filename(name: str, fallback: str = "untitled", max_length: int = 120) -> str:
    normalized = unicodedata.normalize("NFKC", name or "").strip()
    normalized = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip(" .")
    if not normalized:
        normalized = fallback
    if normalized.upper() in WINDOWS_RESERVED_NAMES:
        normalized = f"_{normalized}"
    if len(normalized) > max_length:
        normalized = normalized[:max_length].rstrip(" .")
    return normalized or fallback


def ensure_within_base(base: Path, target: Path) -> Path:
    base_resolved = base.resolve()
    target_resolved = target.resolve()
    try:
        target_resolved.relative_to(base_resolved)
    except ValueError as exc:
        raise EsjSecurityError("目标路径超出插件数据目录") from exc
    return target_resolved


def validate_esj_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise EsjSecurityError("仅允许 HTTPS ESJZone URL")
    if parsed.hostname not in ALLOWED_ESJ_HOSTS:
        raise EsjSecurityError("URL 域名不在 ESJZone 白名单内")
    if parsed.username or parsed.password:
        raise EsjSecurityError("URL 不允许包含用户名或密码")
    if "\\" in url or any(ord(ch) < 32 for ch in url):
        raise EsjSecurityError("URL 包含非法字符")
    return url


def is_allowed_esj_url(url: str) -> bool:
    try:
        validate_esj_url(url)
        return True
    except EsjSecurityError:
        return False


def normalize_domain(domain: str) -> str:
    return (domain or "").strip().lower()


def is_allowed_cookie_domain(domain: str) -> bool:
    return normalize_domain(domain) in ALLOWED_COOKIE_DOMAINS


def mask_email(email: str) -> str:
    if "@" not in email:
        return "***"
    name, domain = email.split("@", 1)
    if len(name) <= 2:
        masked_name = name[:1] + "***"
    else:
        masked_name = name[:2] + "***"
    return f"{masked_name}@{domain}"


def coerce_bool(value: object, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on", "enabled"}
    return bool(value)
