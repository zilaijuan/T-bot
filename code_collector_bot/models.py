from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class TaskStatus(StrEnum):
    NEW = "NEW"
    RUNNING = "RUNNING"
    WAIT = "WAIT"
    DONE = "DONE"
    FAILED = "FAILED"
    RETRY = "RETRY"


@dataclass(frozen=True, slots=True)
class TaskInput:
    user_id: int
    username: str | None
    chat_id: int
    message_id: int
    message_type: str
    message_content: str
    target_worker: str
    telegram_file_id: str | None
    raw_message_json: str


@dataclass(frozen=True, slots=True)
class TaskRecord:
    task_id: int
    user_id: int
    username: str | None
    chat_id: int
    message_id: int
    message_type: str
    message_content: str
    status: TaskStatus
    target_worker: str
    telegram_file_id: str | None
    raw_message_json: str
    state_payload: str
    next_run_at: datetime
    created_at: datetime
    updated_at: datetime