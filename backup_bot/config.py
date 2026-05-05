from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True, slots=True)
class BackupSettings:
    enabled: bool
    bot_token: str
    chat_id: int | None
    interval_seconds: int
    backup_paths: tuple[Path, ...]
    state_path: Path
    delete_old: bool
    caption_prefix: str
    admin_user_ids: frozenset[int]

    @classmethod
    def from_env(cls) -> "BackupSettings":
        load_dotenv()

        enabled = _parse_bool(os.getenv("BACKUP_BOT_ENABLED"), default=False)
        bot_token = os.getenv("BACKUP_BOT_TOKEN", "").strip()
        raw_chat_id = os.getenv("BACKUP_CHAT_ID", "").strip()
        try:
            chat_id = int(raw_chat_id) if raw_chat_id else None
        except ValueError as exc:
            raise RuntimeError("BACKUP_CHAT_ID must be an integer chat ID.") from exc

        raw_paths = os.getenv("BACKUP_PATHS", "data/bots.db")
        backup_paths = tuple(Path(chunk.strip()).expanduser() for chunk in raw_paths.split(",") if chunk.strip())

        settings = cls(
            enabled=enabled,
            bot_token=bot_token,
            chat_id=chat_id,
            interval_seconds=_parse_positive_int(os.getenv("BACKUP_INTERVAL_SECONDS", "3600"), name="BACKUP_INTERVAL_SECONDS"),
            backup_paths=backup_paths,
            state_path=Path(os.getenv("BACKUP_STATE_PATH", "data/backup_state.json")).expanduser(),
            delete_old=_parse_bool(os.getenv("BACKUP_DELETE_OLD"), default=True),
            caption_prefix=os.getenv("BACKUP_CAPTION_PREFIX", "SQLite backup").strip() or "SQLite backup",
            admin_user_ids=_parse_admin_user_ids(os.getenv("BACKUP_ADMIN_USER_IDS", "")),
        )
        if settings.enabled:
            settings.validate()
        return settings

    def validate(self) -> None:
        if not self.bot_token:
            raise RuntimeError("Missing BACKUP_BOT_TOKEN.")
        if self.chat_id is None:
            raise RuntimeError("Missing BACKUP_CHAT_ID.")
        if not self.backup_paths:
            raise RuntimeError("BACKUP_PATHS must contain at least one file path.")


def _parse_positive_int(raw_value: str | None, *, name: str) -> int:
    try:
        value = int((raw_value or "").strip())
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer.") from exc
    if value <= 0:
        raise RuntimeError(f"{name} must be greater than 0.")
    return value


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
            raise RuntimeError("BACKUP_ADMIN_USER_IDS must be comma-separated integers.") from exc
    return frozenset(user_ids)
