from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True, slots=True)
class Settings:
    bot_token: str
    database_path: Path
    upload_dir: Path
    code_length: int
    default_expiry_spec: str
    admin_user_ids: frozenset[int]
    web_enabled: bool
    web_host: str
    web_port: int
    public_base_url: str | None

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()

        bot_token = os.getenv("BOT_TOKEN", "").strip()
        if not bot_token:
            raise RuntimeError("Missing BOT_TOKEN. Create a .env file first.")

        database_path = Path(os.getenv("DATABASE_PATH", "data/bot.db")).expanduser()
        upload_dir = Path(os.getenv("UPLOAD_DIR", "data/uploads")).expanduser()

        raw_code_length = os.getenv("CODE_LENGTH", "8").strip()
        try:
            code_length = int(raw_code_length)
        except ValueError as exc:
            raise RuntimeError("CODE_LENGTH must be an integer.") from exc

        if code_length < 4:
            raise RuntimeError("CODE_LENGTH must be at least 4.")

        default_expiry_spec = os.getenv("DEFAULT_EXPIRY", "forever").strip() or "forever"
        admin_user_ids = _parse_admin_user_ids(os.getenv("ADMIN_USER_IDS", ""))
        web_enabled = _parse_bool(os.getenv("WEB_ENABLED"), default=True)
        web_host = os.getenv("WEB_HOST", "127.0.0.1").strip() or "127.0.0.1"

        raw_web_port = os.getenv("WEB_PORT", "8080").strip()
        try:
            web_port = int(raw_web_port)
        except ValueError as exc:
            raise RuntimeError("WEB_PORT must be an integer.") from exc

        public_base_url = os.getenv("PUBLIC_BASE_URL", "").strip() or None

        return cls(
            bot_token=bot_token,
            database_path=database_path,
            upload_dir=upload_dir,
            code_length=code_length,
            default_expiry_spec=default_expiry_spec,
            admin_user_ids=admin_user_ids,
            web_enabled=web_enabled,
            web_host=web_host,
            web_port=web_port,
            public_base_url=public_base_url,
        )


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

    admin_ids: set[int] = set()
    for chunk in raw_value.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            admin_ids.add(int(chunk))
        except ValueError as exc:
            raise RuntimeError("ADMIN_USER_IDS must be a comma-separated list of integers.") from exc

    return frozenset(admin_ids)
