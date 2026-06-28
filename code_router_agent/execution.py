from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from code_collector_bot.models import TaskStatus


class ExecutionStatus(StrEnum):
    CONTINUE = "CONTINUE"
    WAIT_REPLY = "WAIT_REPLY"
    DONE = "DONE"
    RETRY = "RETRY"
    FAILED = "FAILED"


class NextAction(StrEnum):
    SEND_MESSAGE = "SEND_MESSAGE"
    CLICK_BUTTON = "CLICK_BUTTON"
    CLICK_NEXT_PAGE = "CLICK_NEXT_PAGE"
    WAIT = "WAIT"
    NONE = "NONE"


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    status: ExecutionStatus
    next_action: NextAction = NextAction.NONE
    delay_seconds: float = 0
    state_payload: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] = field(default_factory=dict)

    def to_task_status(self) -> TaskStatus:
        if self.status == ExecutionStatus.DONE:
            return TaskStatus.DONE
        if self.status == ExecutionStatus.FAILED:
            return TaskStatus.FAILED
        if self.status == ExecutionStatus.RETRY:
            return TaskStatus.RETRY
        if self.status == ExecutionStatus.WAIT_REPLY:
            return TaskStatus.WAIT
        return TaskStatus.WAIT