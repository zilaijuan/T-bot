from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True, slots=True)
class Settings:
    bot_token: str
    database_url: str
    database_path: Path
    default_expiry: str
    code_random_length: int
    max_items_per_bundle: int | None
    max_code_summary_length: int | None
    upload_mode: str
    upload_dir: Path
    admin_user_ids: frozenset[int]
    allow_public_upload: bool
    allow_public_redeem: bool
    web_enabled: bool
    public_base_url: str | None

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()

        bot_token = (
            os.getenv("TELEGRAM_FILE_CODE_BOT_TOKEN", "").strip()
            or os.getenv("FILE_CODE_BOT_TOKEN", "").strip()
            or os.getenv("BOT_TOKEN", "").strip()
        )
        if not bot_token:
            raise RuntimeError("Missing TELEGRAM_FILE_CODE_BOT_TOKEN. Create a .env file first.")

        database_url = os.getenv("DATABASE_URL", "").strip()
        legacy_database_path = os.getenv("DATABASE_PATH", "").strip()
        if not database_url:
            database_url = f"sqlite:///{legacy_database_path or 'data/bots.db'}"

        database_path = _sqlite_path_from_url(database_url)

        default_expiry = os.getenv("DEFAULT_EXPIRY", "7d").strip() or "7d"
        code_random_length = _parse_positive_int(
            os.getenv("CODE_RANDOM_LENGTH", os.getenv("CODE_LENGTH", "8")),
            name="CODE_RANDOM_LENGTH",
            minimum=4,
        )

        upload_dir = Path(os.getenv("UPLOAD_DIR", "data/uploads")).expanduser()

        return cls(
            bot_token=bot_token,
            database_url=database_url,
            database_path=database_path,
            default_expiry=default_expiry,
            code_random_length=code_random_length,
            max_items_per_bundle=_parse_optional_limit(os.getenv("MAX_ITEMS_PER_BUNDLE")),
            max_code_summary_length=_parse_optional_limit(os.getenv("MAX_CODE_SUMMARY_LENGTH")),
            upload_mode=os.getenv("UPLOAD_MODE", "telegram_file_id").strip() or "telegram_file_id",
            upload_dir=upload_dir,
            admin_user_ids=_parse_admin_user_ids(os.getenv("ADMIN_USER_IDS", "")),
            allow_public_upload=_parse_bool(os.getenv("ALLOW_PUBLIC_UPLOAD"), default=True),
            allow_public_redeem=_parse_bool(os.getenv("ALLOW_PUBLIC_REDEEM"), default=True),
            web_enabled=_parse_bool(os.getenv("WEB_ENABLED"), default=False),
            public_base_url=os.getenv("PUBLIC_BASE_URL", "").strip() or None,
        )


def _sqlite_path_from_url(database_url: str) -> Path:
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        raise RuntimeError("Only sqlite:/// DATABASE_URL is supported in v1.")
    raw_path = database_url[len(prefix) :]
    if not raw_path:
        raise RuntimeError("DATABASE_URL must include a SQLite database path.")
    return Path(raw_path).expanduser()


def _parse_positive_int(raw_value: str | None, *, name: str, minimum: int) -> int:
    try:
        value = int((raw_value or "").strip())
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer.") from exc
    if value < minimum:
        raise RuntimeError(f"{name} must be at least {minimum}.")
    return value


def _parse_optional_limit(raw_value: str | None) -> int | None:
    if raw_value is None or not raw_value.strip():
        return None
    try:
        value = int(raw_value.strip())
    except ValueError as exc:
        raise RuntimeError("Optional limit values must be integers.") from exc
    return value if value > 0 else None


def _parse_bool(raw_value: str | None, *, default: bool) -> bool:
    if raw_value is None:
        return default
    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _parse_admin_user_ids(raw_value: str) -> frozenset[int]:
    if not raw_value.strip():
        return frozenset()

    user_ids: set[int] = set()
    for chunk in raw_value.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            user_ids.add(int(chunk))
        except ValueError as exc:
            raise RuntimeError("ADMIN_USER_IDS must be comma-separated integers.") from exc
    return frozenset(user_ids)
