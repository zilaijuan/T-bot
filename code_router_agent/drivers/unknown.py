from __future__ import annotations

from code_collector_bot.models import TaskRecord
from code_router_agent.config import CodeRouterAgentSettings
from code_router_agent.execution import ExecutionResult, ExecutionStatus, NextAction


class UnknownDriver:
    def __init__(self, worker_name: str) -> None:
        self.name = worker_name
        self.auto_register = False

    def matches(self, task: TaskRecord, settings: CodeRouterAgentSettings) -> bool:
        return False

    def matched_code(self, task: TaskRecord, settings: CodeRouterAgentSettings) -> str | None:
        return None

    async def step(self, task: TaskRecord, settings: CodeRouterAgentSettings) -> ExecutionResult:
        return ExecutionResult(
            status=ExecutionStatus.FAILED,
            next_action=NextAction.NONE,
            state_payload={"driver": "unknown", "worker": self.name},
            result={"error": f"No driver registered for worker: {self.name}"},
        )