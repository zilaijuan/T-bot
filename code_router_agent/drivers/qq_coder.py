from __future__ import annotations

import asyncio
import re
from dataclasses import asdict, dataclass

from code_collector_bot.models import TaskRecord
from code_router_agent.config import CodeRouterAgentSettings
from code_router_agent.execution import ExecutionResult, ExecutionStatus, NextAction
from code_router_agent.telethon_client import parse_telethon_proxy, send_messages_with_telethon


QQ_CODER_PATTERN = re.compile(
    r"(?P<source_bot>QQ[a-zA-Z0-9]+_bot):(?P<code>qqcode[a-zA-Z0-9]+(?:_[a-zA-Z0-9]+)*)"
)


@dataclass(frozen=True, slots=True)
class QQCoderCode:
    source_bot: str
    code: str
    raw: str


def extract_qq_coder_codes(message_content: str) -> tuple[QQCoderCode, ...]:
    codes: list[QQCoderCode] = []
    seen: set[str] = set()
    for match in QQ_CODER_PATTERN.finditer(message_content):
        raw = match.group(0)
        if raw in seen:
            continue
        seen.add(raw)
        codes.append(
            QQCoderCode(
                source_bot=match.group("source_bot"),
                code=match.group("code"),
                raw=raw,
            )
        )
    return tuple(codes)


class QQCoderDriver:
    name = "qq_coder"
    auto_register = True

    def matches(self, task: TaskRecord, settings: CodeRouterAgentSettings) -> bool:
        return bool(extract_qq_coder_codes(task.message_content))

    def matched_code(self, task: TaskRecord, settings: CodeRouterAgentSettings) -> str | None:
        codes = extract_qq_coder_codes(task.message_content)
        return codes[0].raw if codes else None

    async def step(self, task: TaskRecord, settings: CodeRouterAgentSettings) -> ExecutionResult:
        codes = extract_qq_coder_codes(task.message_content)
        if not codes:
            return ExecutionResult(
                status=ExecutionStatus.FAILED,
                next_action=NextAction.NONE,
                state_payload={"driver": self.name, "matched_codes": []},
                result={"error": "No QQ coder code found in task message."},
            )

        target_bot = settings.qq_coder_target_bot
        message_to_send = task.message_content.strip()
        messages_to_send = (message_to_send,)
        if settings.qq_coder_dry_run:
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
                    "message": "QQ coder codes matched. Dry-run enabled; no Telegram message was sent.",
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
                result={"error": "QQ_CODER_DRIVER_TARGET_BOT is not configured."},
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
            result={"message": "QQ coder message sent to target bot.", "count": len(messages_to_send)},
        )


_parse_telethon_proxy = parse_telethon_proxy