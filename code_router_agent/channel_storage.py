from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class ChannelMessageInput:
    channel_id: int
    channel_username: str | None
    message_id: int
    sender_id: int | None
    message_date: datetime | None
    text: str
    raw_message_json: str


class ChannelMessageRepository:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.database_path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.lock = threading.RLock()

    def init(self) -> None:
        with self.lock:
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS channel_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id INTEGER NOT NULL,
                    channel_username TEXT,
                    message_id INTEGER NOT NULL,
                    sender_id INTEGER,
                    message_date TEXT,
                    text TEXT NOT NULL,
                    raw_message_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(channel_id, message_id)
                )
                """
            )
            self.connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_channel_messages_channel_date ON channel_messages(channel_id, message_date)"
            )
            self.connection.commit()

    def save_message(self, message: ChannelMessageInput) -> bool:
        now = datetime.now(timezone.utc)
        with self.lock:
            cursor = self.connection.execute(
                """
                INSERT OR IGNORE INTO channel_messages (
                    channel_id,
                    channel_username,
                    message_id,
                    sender_id,
                    message_date,
                    text,
                    raw_message_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message.channel_id,
                    message.channel_username,
                    message.message_id,
                    message.sender_id,
                    _to_iso(message.message_date),
                    message.text,
                    message.raw_message_json,
                    _to_iso(now),
                ),
            )
            self.connection.commit()
            return cursor.rowcount > 0


def serialize_telethon_message(message: Any) -> str:
    try:
        raw_value = message.to_dict()
    except Exception:
        raw_value = {"id": getattr(message, "id", None), "text": getattr(message, "raw_text", "")}
    return json.dumps(raw_value, ensure_ascii=False, default=_json_default, sort_keys=True)


def _to_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return _to_iso(value) or ""
    return str(value)
