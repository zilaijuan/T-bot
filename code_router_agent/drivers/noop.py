from __future__ import annotations

from datetime import datetime, timezone

from code_collector_bot.models import TaskRecord
from code_router_agent.config import CodeRouterAgentSettings
from code_router_agent.execution import ExecutionResult, ExecutionStatus, NextAction


class NoopDriver:
    name = "noop"
    auto_register = False

    def matches(self, task: TaskRecord, settings: CodeRouterAgentSettings) -> bool:
        return False

    def matched_code(self, task: TaskRecord, settings: CodeRouterAgentSettings) -> str | None:
        return None

    async def step(self, task: TaskRecord, settings: CodeRouterAgentSettings) -> ExecutionResult:
        return ExecutionResult(
            status=ExecutionStatus.DONE,
            next_action=NextAction.NONE,
            state_payload={
                "driver": self.name,
                "processed_at": datetime.now(timezone.utc).isoformat(),
                "source_task_status": str(task.status),
            },
            result={
                "message": "No concrete driver configured; task was acknowledged by noop driver.",
            },
        )