from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re


CODE_PATTERN = re.compile(r"^[A-Z0-9]{4,64}$")
EXPIRY_PATTERN = re.compile(r"^\s*(\d+)\s*(m|h|d|w)\s*$", re.IGNORECASE)
PERMANENT_ALIASES = {"forever", "permanent", "perm", "never", "infinite"}
PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}


@dataclass(frozen=True, slots=True)
class ExpiryPolicy:
    raw_spec: str
    is_permanent: bool
    expires_at: datetime | None


def parse_expiry_spec(raw_spec: str | None, default_spec: str = "forever") -> ExpiryPolicy:
    spec = (raw_spec or default_spec).strip().lower()
    if not spec:
        spec = default_spec.strip().lower()

    if spec in PERMANENT_ALIASES:
        return ExpiryPolicy(raw_spec="forever", is_permanent=True, expires_at=None)

    matched = EXPIRY_PATTERN.fullmatch(spec)
    if matched is None:
        raise ValueError("有效期格式不正确。示例：30m、12h、7d、4w、forever")

    amount = int(matched.group(1))
    if amount <= 0:
        raise ValueError("有效期必须大于 0。")

    unit = matched.group(2).lower()
    delta_map = {
        "m": timedelta(minutes=amount),
        "h": timedelta(hours=amount),
        "d": timedelta(days=amount),
        "w": timedelta(weeks=amount),
    }

    expires_at = datetime.now(timezone.utc) + delta_map[unit]
    return ExpiryPolicy(raw_spec=f"{amount}{unit}", is_permanent=False, expires_at=expires_at)


def normalize_code(raw_text: str) -> str | None:
    code = raw_text.strip().upper()
    if not CODE_PATTERN.fullmatch(code):
        return None
    return code


def build_deep_link(bot_username: str | None, code: str) -> str | None:
    if not bot_username:
        return None
    return f"https://t.me/{bot_username}?start={code}"


def build_bundle_url(base_url: str | None, code: str) -> str | None:
    if not base_url:
        return None
    return f"{base_url.rstrip('/')}/c/{code}"


def format_datetime(value: str | datetime | None) -> str:
    if value is None:
        return "未设置"

    if isinstance(value, str):
        value = datetime.fromisoformat(value)

    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def format_expiry_label(*, is_permanent: bool, expires_at: str | datetime | None) -> str:
    if is_permanent:
        return "永久有效"
    return f"到 {format_datetime(expires_at)}"


def guess_media_type(file_name: str | None, mime_type: str | None) -> str:
    suffix = Path(file_name or "").suffix.lower()

    if mime_type and mime_type.startswith("video/"):
        return "video"

    if mime_type and mime_type.startswith("image/") and suffix in PHOTO_EXTENSIONS:
        return "photo"

    if suffix in PHOTO_EXTENSIONS:
        return "photo"

    if suffix in VIDEO_EXTENSIONS:
        return "video"

    return "document"
