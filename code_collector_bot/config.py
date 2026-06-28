from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True, slots=True)
class CodeCollectorSettings:
    enabled: bool
    bot_token: str
    database_url: str
    database_path: Path
    default_worker: str
    admin_user_ids: frozenset[int]
    allow_public_submit: bool
    proxy_url: str | None

    @classmethod
    def from_env(cls) -> "CodeCollectorSettings":
        load_dotenv()

        enabled = _parse_bool(os.getenv("CODE_COLLECTOR_BOT_ENABLED", os.getenv("CODE_COLLECTOR_ENABLED")), default=False)
        bot_token = os.getenv("CODE_COLLECTOR_BOT_TOKEN", "").strip() or os.getenv("CODE_COLLECTOR_TOKEN", "").strip()
        database_url = os.getenv("DATABASE_URL", "sqlite:///data/bot.db").strip() or "sqlite:///data/bot.db"

        settings = cls(
            enabled=enabled,
            bot_token=bot_token,
            database_url=database_url,
            database_path=_sqlite_path_from_url(database_url),
            default_worker=(os.getenv("CODE_COLLECTOR_BOT_DEFAULT_WORKER", "").strip() or os.getenv("CODE_COLLECTOR_DEFAULT_WORKER", "pending").strip() or "pending"),
            admin_user_ids=_parse_admin_user_ids(os.getenv("CODE_COLLECTOR_BOT_ADMIN_USER_IDS", os.getenv("CODE_COLLECTOR_ADMIN_USER_IDS", ""))),
            allow_public_submit=_parse_bool(os.getenv("CODE_COLLECTOR_BOT_ALLOW_PUBLIC_SUBMIT", os.getenv("CODE_COLLECTOR_ALLOW_PUBLIC_SUBMIT")), default=True),
            proxy_url=(
                os.getenv("CODE_COLLECTOR_BOT_PROXY_URL", "").strip()
                or os.getenv("TELEGRAM_PROXY_URL", "").strip()
                or os.getenv("PROXY_URL", "").strip()
                or None
            ),
        )
        if settings.enabled:
            settings.validate()
        return settings

    def validate(self) -> None:
        if not self.bot_token:
            raise RuntimeError("Missing CODE_COLLECTOR_BOT_TOKEN.")


def _sqlite_path_from_url(database_url: str) -> Path:
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        raise RuntimeError("Only sqlite:/// DATABASE_URL is supported by code_collector_bot.")
    raw_path = database_url[len(prefix) :]
    if not raw_path:
        raise RuntimeError("DATABASE_URL must include a SQLite database path.")
    return Path(raw_path).expanduser()


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
            raise RuntimeError("CODE_COLLECTOR_BOT_ADMIN_USER_IDS must be comma-separated integers.") from exc
    return frozenset(user_ids)
