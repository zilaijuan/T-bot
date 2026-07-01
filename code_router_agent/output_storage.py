from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from code_router_agent.execution import DriverOutputMessage


OUTPUT_TASK_STATUS_NEW = "NEW"


class DriverOutputRepository:
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
            self._migrate_output_messages_schema()
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
            self._backfill_output_tasks()
            self.connection.commit()

    def _migrate_output_messages_schema(self) -> None:
        columns = [
            str(row["name"])
            for row in self.connection.execute("PRAGMA table_info(driver_output_messages)").fetchall()
        ]
        if "status" not in columns:
            return
        self.connection.execute("ALTER TABLE driver_output_messages RENAME TO driver_output_messages_old")
        self.connection.execute(
            """
            CREATE TABLE driver_output_messages (
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
            INSERT OR IGNORE INTO driver_output_messages (
                output_id,
                task_id,
                source,
                source_message_id,
                content,
                raw_payload,
                created_at,
                updated_at
            )
            SELECT
                output_id,
                task_id,
                source,
                source_message_id,
                content,
                raw_payload,
                created_at,
                updated_at
            FROM driver_output_messages_old
            """
        )
        self.connection.execute("DROP TABLE driver_output_messages_old")

    def _backfill_output_tasks(self) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.connection.execute(
            """
            INSERT OR IGNORE INTO driver_output_tasks (
                task_id,
                status,
                created_at,
                updated_at
            )
            SELECT DISTINCT
                task_id,
                ?,
                ?,
                ?
            FROM driver_output_messages
            """,
            (OUTPUT_TASK_STATUS_NEW, now, now),
        )

    def save_messages(self, task_id: int, messages: tuple[DriverOutputMessage, ...]) -> int:
        if not messages:
            return 0
        now = datetime.now(timezone.utc).isoformat()
        saved_count = 0
        with self.lock:
            for message in messages:
                cursor = self.connection.execute(
                    """
                    INSERT OR IGNORE INTO driver_output_messages (
                        task_id,
                        source,
                        source_message_id,
                        content,
                        raw_payload,
                        created_at,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        task_id,
                        message.source,
                        message.message_id,
                        message.content,
                        json.dumps(message.raw_payload, ensure_ascii=False, sort_keys=True),
                        now,
                        now,
                    ),
                )
                saved_count += cursor.rowcount
            self.connection.execute(
                """
                INSERT OR IGNORE INTO driver_output_tasks (
                    task_id,
                    status,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?)
                """,
                (task_id, OUTPUT_TASK_STATUS_NEW, now, now),
            )
            self.connection.commit()
        return saved_count
