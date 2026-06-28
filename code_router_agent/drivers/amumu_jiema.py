from __future__ import annotations

import asyncio
import re
from dataclasses import asdict, dataclass

from code_collector_bot.models import TaskRecord
from code_router_agent.config import CodeRouterAgentSettings
from code_router_agent.execution import ExecutionResult, ExecutionStatus, NextAction
from code_router_agent.telethon_client import send_messages_with_telethon


AMUMU_JIEMA_PATTERN = re.compile(r"(?<![A-Za-z0-9_])(?P<code>amumujiemabot_[A-Za-z0-9]+)(?![A-Za-z0-9_])")


@dataclass(frozen=True, slots=True)
class AmumuJiemaCode:
    code: str


def extract_amumu_jiema_codes(message_content: str) -> tuple[AmumuJiemaCode, ...]:
    codes: list[AmumuJiemaCode] = []
    seen: set[str] = set()
    for match in AMUMU_JIEMA_PATTERN.finditer(message_content):
        code = match.group("code")
        if code in seen:
            continue
        seen.add(code)
        codes.append(AmumuJiemaCode(code=code))
    return tuple(codes)


class AmumuJiemaDriver:
    name = "amumu_jiema"
    auto_register = True

    def matches(self, task: TaskRecord, settings: CodeRouterAgentSettings) -> bool:
        return bool(extract_amumu_jiema_codes(task.message_content))

    async def step(self, task: TaskRecord, settings: CodeRouterAgentSettings) -> ExecutionResult:
        codes = extract_amumu_jiema_codes(task.message_content)
        if not codes:
            return ExecutionResult(
                status=ExecutionStatus.FAILED,
                next_action=NextAction.NONE,
                state_payload={"driver": self.name, "matched_codes": []},
                result={"error": "No amumu jiema code found in task message."},
            )

        target_bot = settings.amumu_jiema_target_bot
        message_to_send = task.message_content.strip()
        messages_to_send = (message_to_send,)
        if settings.amumu_jiema_dry_run:
            return ExecutionResult(
                status=ExecutionStatus.DONE,
                next_action=NextAction.SEND_MESSAGE,
                state_payload={
                    "driver": self.name,
                    "dry_run": True,
                    "target_bot": target_bot,
                    "matched_codes": [asdict(code) for code in codes],
                    "messages_to_send": list(messages_to_send),
                },
                result={
                    "message": "amumu jiema codes matched. Dry-run enabled; no Telegram message was sent.",
                    "count": len(messages_to_send),
                },
            )

        if not target_bot:
            return ExecutionResult(
                status=ExecutionStatus.FAILED,
                next_action=NextAction.NONE,
                state_payload={
                    "driver": self.name,
                    "dry_run": False,
                    "matched_codes": [asdict(code) for code in codes],
                },
                result={"error": "AMUMU_JIEMA_DRIVER_TARGET_BOT is not configured."},
            )

        await asyncio.wait_for(
            send_messages_with_telethon(target_bot, messages_to_send, settings),
            timeout=settings.telethon_timeout_seconds,
        )
        return ExecutionResult(
            status=ExecutionStatus.DONE,
            next_action=NextAction.SEND_MESSAGE,
            state_payload={
                "driver": self.name,
                "dry_run": False,
                "target_bot": target_bot,
                "matched_codes": [asdict(code) for code in codes],
                "messages_to_send": list(messages_to_send),
            },
            result={"message": "amumu jiema message sent to target bot.", "count": len(messages_to_send)},
        )