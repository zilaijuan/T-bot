from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True, slots=True)
class MessageDispatchSettings:
    enabled: bool
    bot_token: str
    database_url: str
    database_path: Path
    interval_seconds: int
    max_tasks_per_run: int
    admin_user_ids: frozenset[int]
    proxy_url: str | None

    @classmethod
    def from_env(cls) -> "MessageDispatchSettings":
        load_dotenv()
        database_url = os.getenv("DATABASE_URL", "sqlite:///data/bot.db").strip() or "sqlite:///data/bot.db"
        return cls(
            enabled=_parse_bool(os.getenv("MESSAGE_DISPATCH_BOT_ENABLED"), default=False),
            bot_token=os.getenv("MESSAGE_DISPATCH_BOT_TOKEN", "").strip(),
            database_url=database_url,
            database_path=_sqlite_path_from_url(database_url),
            interval_seconds=_parse_positive_int(
                os.getenv("MESSAGE_DISPATCH_INTERVAL_SECONDS", "300"),
                name="MESSAGE_DISPATCH_INTERVAL_SECONDS",
            ),
            max_tasks_per_run=_parse_positive_int(
                os.getenv("MESSAGE_DISPATCH_MAX_TASKS_PER_RUN", "20"),
                name="MESSAGE_DISPATCH_MAX_TASKS_PER_RUN",
            ),
            admin_user_ids=_parse_admin_user_ids(os.getenv("MESSAGE_DISPATCH_ADMIN_USER_IDS", "")),
            proxy_url=(
                os.getenv("MESSAGE_DISPATCH_BOT_PROXY_URL", "").strip()
                or os.getenv("TELEGRAM_PROXY_URL", "").strip()
                or os.getenv("PROXY_URL", "").strip()
                or None
            ),
        )

    def validate(self) -> None:
        if self.enabled and not self.bot_token:
            raise RuntimeError("Missing MESSAGE_DISPATCH_BOT_TOKEN when MESSAGE_DISPATCH_BOT_ENABLED=true.")


def _sqlite_path_from_url(database_url: str) -> Path:
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        raise RuntimeError("Only sqlite:/// DATABASE_URL is supported by message_dispatch_bot.")
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


def _parse_positive_int(raw_value: str | None, *, name: str) -> int:
    try:
        value = int((raw_value or "").strip())
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer.") from exc
    if value <= 0:
        raise RuntimeError(f"{name} must be greater than 0.")
    return value


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
            raise RuntimeError("MESSAGE_DISPATCH_ADMIN_USER_IDS must be comma-separated integers.") from exc
    return frozenset(user_ids)
