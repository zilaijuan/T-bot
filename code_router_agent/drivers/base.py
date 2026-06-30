from __future__ import annotations

from typing import Protocol

from code_collector_bot.models import TaskRecord
from code_router_agent.config import CodeRouterAgentSettings
from code_router_agent.execution import ExecutionResult


class Driver(Protocol):
    name: str
    auto_register: bool

    def matches(self, task: TaskRecord, settings: CodeRouterAgentSettings) -> bool:
        """Return whether this driver can handle the task."""

    def matched_code(self, task: TaskRecord, settings: CodeRouterAgentSettings) -> str | None:
        """Return the code used for duplicate detection after this driver matches."""

    async def step(self, task: TaskRecord, settings: CodeRouterAgentSettings) -> ExecutionResult:
        """Execute one state-machine step for a task."""
