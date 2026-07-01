from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


SUBSCRIBER_ACTIVE = "ACTIVE"
SUBSCRIBER_INACTIVE = "INACTIVE"
SUBSCRIBER_BLOCKED = "BLOCKED"
OUTPUT_TASK_NEW = "NEW"
OUTPUT_TASK_RUNNING = "RUNNING"
OUTPUT_TASK_DONE = "DONE"
OUTPUT_TASK_FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class SubscriberRecord:
    user_id: int
    chat_id: int
    username: str | None
    first_name: str | None
    last_name: str | None
    status: str


@dataclass(frozen=True, slots=True)
class DriverOutputMessageRecord:
    output_id: int
    content: str


@dataclass(frozen=True, slots=True)
class DispatchPayload:
    task_id: int
    original_text: str
    output_messages: tuple[DriverOutputMessageRecord, ...]


class MessageDispatchRepository:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.database_path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.lock = threading.RLock()

    def init(self) -> None:
        with self.lock:
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS message_dispatch_subscribers (
                    subscriber_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL UNIQUE,
                    chat_id INTEGER NOT NULL,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self.connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_message_dispatch_subscribers_status ON message_dispatch_subscribers(status)"
            )
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS driver_output_messages (
                    output_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER NOT NULL,
                    source TEXT NOT NULL,
                    source_message_id INTEGER,
                    content TEXT NOT NULL,
                    raw_payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(task_id, source, source_message_id)
                )
                """
            )
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS driver_output_tasks (
                    output_task_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self.connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_driver_output_messages_task_id ON driver_output_messages(task_id)"
            )
            self.connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_driver_output_tasks_status ON driver_output_tasks(status, created_at)"
            )
            self.connection.commit()

    def upsert_subscriber(
        self,
        *,
        user_id: int,
        chat_id: int,
        username: str | None,
        first_name: str | None,
        last_name: str | None,
    ) -> None:
        now = _now_iso()
        with self.lock:
            self.connection.execute(
                """
                INSERT INTO message_dispatch_subscribers (
                    user_id,
                    chat_id,
                    username,
                    first_name,
                    last_name,
                    status,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    chat_id = excluded.chat_id,
                    username = excluded.username,
                    first_name = excluded.first_name,
                    last_name = excluded.last_name,
                    status = excluded.status,
                    updated_at = excluded.updated_at
                """,
                (user_id, chat_id, username, first_name, last_name, SUBSCRIBER_ACTIVE, now, now),
            )
            self.connection.commit()

    def update_subscriber_status(self, user_id: int, status: str) -> None:
        with self.lock:
            self.connection.execute(
                "UPDATE message_dispatch_subscribers SET status = ?, updated_at = ? WHERE user_id = ?",
                (status, _now_iso(), user_id),
            )
            self.connection.commit()

    def list_active_subscribers(self) -> tuple[SubscriberRecord, ...]:
        with self.lock:
            rows = self.connection.execute(
                """
                SELECT user_id, chat_id, username, first_name, last_name, status
                FROM message_dispatch_subscribers
                WHERE status = ?
                ORDER BY subscriber_id ASC
                """,
                (SUBSCRIBER_ACTIVE,),
            ).fetchall()
        return tuple(_subscriber_from_row(row) for row in rows)

    def subscriber_counts(self) -> dict[str, int]:
        with self.lock:
            rows = self.connection.execute(
                "SELECT status, COUNT(*) AS total FROM message_dispatch_subscribers GROUP BY status"
            ).fetchall()
        return {str(row["status"]): int(row["total"]) for row in rows}

    def claim_next_output_task(self) -> int | None:
        now = _now_iso()
        with self.lock:
            row = self.connection.execute(
                """
                SELECT output_task_id, task_id
                FROM driver_output_tasks
                WHERE status = ?
                ORDER BY created_at ASC, output_task_id ASC
                LIMIT 1
                """,
                (OUTPUT_TASK_NEW,),
            ).fetchone()
            if row is None:
                return None
            self.connection.execute(
                "UPDATE driver_output_tasks SET status = ?, updated_at = ? WHERE output_task_id = ? AND status = ?",
                (OUTPUT_TASK_RUNNING, now, int(row["output_task_id"]), OUTPUT_TASK_NEW),
            )
            self.connection.commit()
            return int(row["task_id"])

    def get_payload(self, task_id: int) -> DispatchPayload | None:
        with self.lock:
            task = self.connection.execute(
                "SELECT task_id, message_content FROM workflow_tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            if task is None:
                return None
            rows = self.connection.execute(
                """
                SELECT output_id, content
                FROM driver_output_messages
                WHERE task_id = ?
                ORDER BY output_id ASC
                """,
                (task_id,),
            ).fetchall()
        return DispatchPayload(
            task_id=int(task["task_id"]),
            original_text=str(task["message_content"] or ""),
            output_messages=tuple(
                DriverOutputMessageRecord(output_id=int(row["output_id"]), content=str(row["content"] or ""))
                for row in rows
            ),
        )

    def update_output_task_status(self, task_id: int, status: str) -> None:
        with self.lock:
            self.connection.execute(
                "UPDATE driver_output_tasks SET status = ?, updated_at = ? WHERE task_id = ?",
                (status, _now_iso(), task_id),
            )
            self.connection.commit()


def _subscriber_from_row(row: sqlite3.Row) -> SubscriberRecord:
    return SubscriberRecord(
        user_id=int(row["user_id"]),
        chat_id=int(row["chat_id"]),
        username=row["username"],
        first_name=row["first_name"],
        last_name=row["last_name"],
        status=row["status"],
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
