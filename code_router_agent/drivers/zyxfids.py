from __future__ import annotations

import asyncio
import re
from dataclasses import asdict, dataclass

from code_collector_bot.models import TaskRecord
from code_router_agent.config import CodeRouterAgentSettings
from code_router_agent.execution import ExecutionResult, ExecutionStatus, NextAction
from code_router_agent.telethon_client import send_messages_with_telethon


ZYXFIDS_BOT_USERNAME = "zyxfids_bot"
HEX_CODE_PATTERN = re.compile(r"(?<![A-Fa-f0-9])(?P<code>[A-Fa-f0-9]{40})(?![A-Fa-f0-9])")
TOKEN_CODE_PATTERN = re.compile(r"(?<![A-Za-z0-9])(?P<code>[A-Za-z0-9]{32,96})(?![A-Za-z0-9])")


@dataclass(frozen=True, slots=True)
class ZyxFidsCode:
    code_type: str
    code: str


def extract_zyxfids_codes(message_content: str) -> tuple[ZyxFidsCode, ...]:
    codes: list[ZyxFidsCode] = []
    seen: set[str] = set()

    for match in HEX_CODE_PATTERN.finditer(message_content):
        code = match.group("code")
        if code not in seen:
            seen.add(code)
            codes.append(ZyxFidsCode(code_type="hex40", code=code))

    for match in TOKEN_CODE_PATTERN.finditer(message_content):
        code = match.group("code")
        if code in seen or code.lower() == ZYXFIDS_BOT_USERNAME:
            continue
        if HEX_CODE_PATTERN.fullmatch(code):
            continue
        seen.add(code)
        codes.append(ZyxFidsCode(code_type="token", code=code))

    return tuple(codes)


class ZyxFidsDriver:
    name = "zyxfids"
    auto_register = True

    def matches(self, task: TaskRecord, settings: CodeRouterAgentSettings) -> bool:
        content = task.message_content
        return ZYXFIDS_BOT_USERNAME in content.lower() or bool(extract_zyxfids_codes(content))

    def matched_code(self, task: TaskRecord, settings: CodeRouterAgentSettings) -> str | None:
        codes = extract_zyxfids_codes(task.message_content)
        if codes:
            return codes[0].code
        if ZYXFIDS_BOT_USERNAME in task.message_content.lower():
            return task.message_content.strip()
        return None

    async def step(self, task: TaskRecord, settings: CodeRouterAgentSettings) -> ExecutionResult:
        codes = extract_zyxfids_codes(task.message_content)
        if not codes and ZYXFIDS_BOT_USERNAME in task.message_content.lower():
            codes = (ZyxFidsCode(code_type="raw_text", code=task.message_content.strip()),)

        if not codes:
            return ExecutionResult(
                status=ExecutionStatus.FAILED,
                next_action=NextAction.NONE,
                state_payload={"driver": self.name, "matched_codes": []},
                result={"error": "No zyxfids code found in task message."},
            )

        target_bot = settings.zyxfids_target_bot
        message_to_send = task.message_content.strip()
        messages_to_send = (message_to_send,)
        if settings.zyxfids_dry_run:
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
                    "message": "zyxfids codes matched. Dry-run enabled; no Telegram message was sent.",
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
                result={"error": "ZYXFIDS_DRIVER_TARGET_BOT is not configured."},
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
            result={"message": "zyxfids message sent to target bot.", "count": len(messages_to_send)},
        )