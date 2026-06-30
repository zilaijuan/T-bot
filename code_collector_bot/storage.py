from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from code_collector_bot.models import TaskInput, TaskRecord, TaskStatus


SCHEDULED_STATUSES = (TaskStatus.NEW, TaskStatus.WAIT, TaskStatus.RETRY)


class TaskRepository:
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
                CREATE TABLE IF NOT EXISTS workflow_tasks (
                    task_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT,
                    user_id INTEGER NOT NULL,
                    username TEXT,
                    chat_id INTEGER NOT NULL,
                    message_id INTEGER NOT NULL,
                    message_type TEXT NOT NULL,
                    message_content TEXT NOT NULL,
                    status TEXT NOT NULL,
                    target_worker TEXT NOT NULL,
                    telegram_file_id TEXT,
                    raw_message_json TEXT NOT NULL,
                    state_payload TEXT NOT NULL,
                    next_run_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._migrate_schema()
            self.connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_workflow_tasks_schedule ON workflow_tasks(status, next_run_at)"
            )
            self.connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_workflow_tasks_target_worker ON workflow_tasks(target_worker, status)"
            )
            self.connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_workflow_tasks_user_id ON workflow_tasks(user_id, created_at)"
            )
            self.connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_workflow_tasks_code_status ON workflow_tasks(code, status)"
            )
            self.connection.commit()

    def _migrate_schema(self) -> None:
        columns = {
            str(row["name"])
            for row in self.connection.execute("PRAGMA table_info(workflow_tasks)").fetchall()
        }
        if "code" not in columns:
            self.connection.execute("ALTER TABLE workflow_tasks ADD COLUMN code TEXT")

    def create_task(self, task: TaskInput) -> TaskRecord:
        now = datetime.now(timezone.utc)
        with self.lock:
            cursor = self.connection.execute(
                """
                INSERT INTO workflow_tasks (
                    user_id,
                    username,
                    chat_id,
                    message_id,
                    message_type,
                    message_content,
                    status,
                    target_worker,
                    telegram_file_id,
                    raw_message_json,
                    state_payload,
                    next_run_at,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task.user_id,
                    task.username,
                    task.chat_id,
                    task.message_id,
                    task.message_type,
                    task.message_content,
                    TaskStatus.NEW.value,
                    task.target_worker,
                    task.telegram_file_id,
                    task.raw_message_json,
                    "{}",
                    _to_iso(now),
                    _to_iso(now),
                    _to_iso(now),
                ),
            )
            self.connection.commit()
            task_id = int(cursor.lastrowid)
        record = self.get_task(task_id)
        if record is None:
            raise RuntimeError("Task was created but could not be loaded.")
        return record

    def get_task(self, task_id: int) -> TaskRecord | None:
        with self.lock:
            row = self.connection.execute(
                "SELECT * FROM workflow_tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        return _task_from_row(row) if row is not None else None

    def claim_next_due_task(self, target_worker: str, *, now: datetime | None = None) -> TaskRecord | None:
        return self._claim_next_due_task(target_worker=target_worker, now=now)

    def claim_next_due_task_for_routing(self, *, now: datetime | None = None) -> TaskRecord | None:
        return self._claim_next_due_task(target_worker=None, now=now)

    def _claim_next_due_task(self, *, target_worker: str | None, now: datetime | None = None) -> TaskRecord | None:
        current_time = now or datetime.now(timezone.utc)
        status_values = tuple(status.value for status in SCHEDULED_STATUSES)
        placeholders = ", ".join("?" for _ in status_values)
        target_filter = "AND target_worker = ?" if target_worker is not None else ""
        params: tuple[object, ...]
        if target_worker is None:
            params = (*status_values, _to_iso(current_time))
        else:
            params = (*status_values, _to_iso(current_time), target_worker)

        with self.lock:
            row = self.connection.execute(
                f"""
                SELECT * FROM workflow_tasks
                WHERE status IN ({placeholders})
                  AND next_run_at <= ?
                  {target_filter}
                ORDER BY next_run_at ASC, task_id ASC
                LIMIT 1
                """,
                params,
            ).fetchone()
            if row is None:
                return None

            task_id = int(row["task_id"])
            self.connection.execute(
                "UPDATE workflow_tasks SET status = ?, updated_at = ? WHERE task_id = ?",
                (TaskStatus.RUNNING.value, _to_iso(current_time), task_id),
            )
            self.connection.commit()

        return self.get_task(task_id)

    def update_task_state(
        self,
        task_id: int,
        *,
        status: TaskStatus,
        state_payload: str,
        next_run_at: datetime | None = None,
        target_worker: str | None = None,
        code: str | None = None,
    ) -> TaskRecord | None:
        now = datetime.now(timezone.utc)
        schedule_time = next_run_at or now
        with self.lock:
            self.connection.execute(
                """
                UPDATE workflow_tasks
                SET status = ?,
                    state_payload = ?,
                    next_run_at = ?,
                    target_worker = COALESCE(?, target_worker),
                    code = COALESCE(?, code),
                    updated_at = ?
                WHERE task_id = ?
                """,
                (status.value, state_payload, _to_iso(schedule_time), target_worker, code, _to_iso(now), task_id),
            )
            self.connection.commit()
        return self.get_task(task_id)

    def list_tasks_missing_code(self, *, limit: int = 1000) -> tuple[TaskRecord, ...]:
        with self.lock:
            rows = self.connection.execute(
                """
                SELECT * FROM workflow_tasks
                WHERE code IS NULL OR code = ''
                ORDER BY task_id ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return tuple(_task_from_row(row) for row in rows)

    def update_task_code(self, task_id: int, code: str) -> TaskRecord | None:
        now = datetime.now(timezone.utc)
        with self.lock:
            self.connection.execute(
                """
                UPDATE workflow_tasks
                SET code = ?, updated_at = ?
                WHERE task_id = ?
                """,
                (code, _to_iso(now), task_id),
            )
            self.connection.commit()
        return self.get_task(task_id)

    def find_done_task_by_code(self, code: str, *, exclude_task_id: int | None = None) -> TaskRecord | None:
        if exclude_task_id is None:
            query = "SELECT * FROM workflow_tasks WHERE code = ? AND status = ? ORDER BY updated_at DESC, task_id DESC LIMIT 1"
            params: tuple[object, ...] = (code, TaskStatus.DONE.value)
        else:
            query = "SELECT * FROM workflow_tasks WHERE code = ? AND status = ? AND task_id <> ? ORDER BY updated_at DESC, task_id DESC LIMIT 1"
            params = (code, TaskStatus.DONE.value, exclude_task_id)
        with self.lock:
            row = self.connection.execute(query, params).fetchone()
        return _task_from_row(row) if row is not None else None

    def count_by_status(self) -> dict[str, int]:
        with self.lock:
            rows = self.connection.execute(
                "SELECT status, COUNT(*) AS total FROM workflow_tasks GROUP BY status"
            ).fetchall()
        return {str(row["status"]): int(row["total"]) for row in rows}


def _task_from_row(row: sqlite3.Row) -> TaskRecord:
    return TaskRecord(
        task_id=int(row["task_id"]),
        code=row["code"],
        user_id=int(row["user_id"]),
        username=row["username"],
        chat_id=int(row["chat_id"]),
        message_id=int(row["message_id"]),
        message_type=row["message_type"],
        message_content=row["message_content"],
        status=TaskStatus(row["status"]),
        target_worker=row["target_worker"],
        telegram_file_id=row["telegram_file_id"],
        raw_message_json=row["raw_message_json"],
        state_payload=row["state_payload"],
        next_run_at=datetime.fromisoformat(row["next_run_at"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def _to_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()