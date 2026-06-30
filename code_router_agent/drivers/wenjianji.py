from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from code_collector_bot.models import TaskRecord
from code_router_agent.config import CodeRouterAgentSettings
from code_router_agent.execution import ExecutionResult, ExecutionStatus, NextAction
from code_router_agent.telethon_client import build_telethon_client


LOGGER = logging.getLogger(__name__)
COMPLETE_STOP_REASONS = {"last_page_reached", "next_button_not_found", "all_files_done"}
RESUMABLE_STOP_REASONS = {"no_reply_after_send", "no_page_update_after_click"}
WENJIANJI_PATTERN = re.compile(r"(?<![A-Za-z0-9_])(?P<code>wenjianjibot_[A-Za-z0-9_]+)(?![A-Za-z0-9_])", re.IGNORECASE)
PAGE_PATTERN = re.compile("\u7b2c\\s*(?P<current>\\d+)\\s*/\\s*(?P<total>\\d+)\\s*\u7ec4")
NEXT_PAGE_BUTTON_TEXT = "\u83b7\u53d6\u4e0b\u4e00\u7ec4"
DONE_MESSAGE_MARKERS = ("\u6587\u4ef6\u5168\u90e8\u53d6\u5b8c", "\u5168\u90e8\u53d6\u5b8c")


@dataclass(frozen=True, slots=True)
class WenJianJiCode:
    code: str


@dataclass(frozen=True, slots=True)
class PageSummary:
    message_id: int
    text: str
    current_page: int | None
    total_pages: int | None
    has_next_button: bool


def extract_wenjianji_codes(message_content: str) -> tuple[WenJianJiCode, ...]:
    codes: list[WenJianJiCode] = []
    seen: set[str] = set()
    for match in WENJIANJI_PATTERN.finditer(message_content):
        code = match.group("code")
        normalized = code.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        codes.append(WenJianJiCode(code=code))
    return tuple(codes)


class WenJianJiDriver:
    name = "wenjianji"
    auto_register = True

    def matches(self, task: TaskRecord, settings: CodeRouterAgentSettings) -> bool:
        return bool(extract_wenjianji_codes(task.message_content))

    def matched_code(self, task: TaskRecord, settings: CodeRouterAgentSettings) -> str | None:
        codes = extract_wenjianji_codes(task.message_content)
        return codes[0].code if codes else None

    async def step(self, task: TaskRecord, settings: CodeRouterAgentSettings) -> ExecutionResult:
        codes = extract_wenjianji_codes(task.message_content)
        if not codes:
            return ExecutionResult(
                status=ExecutionStatus.FAILED,
                next_action=NextAction.NONE,
                state_payload={"driver": self.name, "matched_codes": []},
                result={"error": "No WenJianJi code found in task message."},
            )

        target_bot = settings.wenjianji_target_bot
        message_to_send = task.message_content.strip()
        messages_to_send = (message_to_send,)
        if settings.wenjianji_dry_run:
            return ExecutionResult(
                status=ExecutionStatus.DONE,
                next_action=NextAction.SEND_MESSAGE,
                state_payload={
                    "driver": self.name,
                    "dry_run": True,
                    "target_bot": target_bot,
                    "matched_codes": [asdict(code) for code in codes],
                    "messages_to_send": list(messages_to_send),
                    "pagination": {"enabled": True, "dry_run": True},
                },
                result={
                    "message": "WenJianJi code matched. Dry-run enabled; no Telegram message was sent.",
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
                result={"error": "WENJIANJI_DRIVER_TARGET_BOT is not configured."},
            )

        previous_pagination = _load_previous_pagination(task.state_payload)
        if _is_completed_pagination(previous_pagination):
            LOGGER.info(
                "WenJianJi task already has completed pagination stop_reason=%s; skipping send.",
                previous_pagination.get("stop_reason"),
            )
            return ExecutionResult(
                status=ExecutionStatus.DONE,
                next_action=NextAction.NONE,
                state_payload={
                    "driver": self.name,
                    "dry_run": False,
                    "target_bot": target_bot,
                    "matched_codes": [asdict(code) for code in codes],
                    "messages_to_send": list(messages_to_send),
                    "pagination": previous_pagination,
                    "already_completed": True,
                },
                result={
                    "message": "WenJianJi pagination was already completed; no Telegram message was sent.",
                    "count": 0,
                    "pages_seen": previous_pagination.get("pages_seen"),
                    "stop_reason": previous_pagination.get("stop_reason"),
                    "completed": True,
                    "already_completed": True,
                },
            )

        should_resume = _should_resume_pagination(previous_pagination)
        if should_resume:
            pagination = await asyncio.wait_for(
                _resume_click_all_pages(target_bot, previous_pagination, settings),
                timeout=settings.telethon_timeout_seconds * max(settings.wenjianji_max_pages, 1),
            )
        else:
            pagination = await asyncio.wait_for(
                _send_and_click_all_pages(target_bot, message_to_send, settings),
                timeout=settings.telethon_timeout_seconds * max(settings.wenjianji_max_pages, 1),
            )
        completed = pagination["stop_reason"] in COMPLETE_STOP_REASONS
        status = ExecutionStatus.DONE if completed else ExecutionStatus.RETRY
        return ExecutionResult(
            status=status,
            next_action=NextAction.CLICK_NEXT_PAGE,
            state_payload={
                "driver": self.name,
                "dry_run": False,
                "target_bot": target_bot,
                "matched_codes": [asdict(code) for code in codes],
                "messages_to_send": list(messages_to_send),
                "pagination": pagination,
            },
            result={
                "message": "WenJianJi message sent and paginated replies were requested.",
                "count": len(messages_to_send),
                "pages_seen": pagination["pages_seen"],
                "stop_reason": pagination["stop_reason"],
                "completed": completed,
            },
        )


def _load_previous_pagination(raw_state_payload: str) -> dict[str, Any] | None:
    try:
        state = json.loads(raw_state_payload or "{}")
    except json.JSONDecodeError:
        return None
    if not isinstance(state, dict):
        return None
    pagination = state.get("pagination")
    return pagination if isinstance(pagination, dict) else None


def _should_resume_pagination(pagination: dict[str, Any] | None) -> bool:
    if not pagination:
        return False
    return pagination.get("stop_reason") in RESUMABLE_STOP_REASONS

def _is_completed_pagination(pagination: dict[str, Any] | None) -> bool:
    if not pagination:
        return False
    return pagination.get("stop_reason") in COMPLETE_STOP_REASONS


async def _resume_click_all_pages(target_bot: str, previous_pagination: dict[str, Any], settings: CodeRouterAgentSettings) -> dict[str, Any]:
    async with build_telethon_client(settings) as client:
        if not await client.is_user_authorized():
            raise RuntimeError("Telethon session is not authorized. Log in once before enabling real sends.")

        entity = await client.get_entity(target_bot)
        sent_message_id = int(previous_pagination.get("sent_message_id") or 0)
        pages = previous_pagination.get("pages") or []
        last_page = pages[-1] if pages else {}
        last_message_id = int(last_page.get("message_id") or sent_message_id)
        LOGGER.info(
            "WenJianJi resuming pagination for sent_message_id=%s from last_message_id=%s stop_reason=%s.",
            sent_message_id,
            last_message_id,
            previous_pagination.get("stop_reason"),
        )
        expected_next_page = None
        if isinstance(last_page, dict):
            current_page = last_page.get("current_page")
            expected_next_page = int(current_page) + 1 if isinstance(current_page, int) else None
        current_message = await _find_existing_page_message_after(
            client,
            entity,
            after_id=last_message_id,
            expected_current_page=expected_next_page,
        )
        if current_message is None:
            current_message = await client.get_messages(entity, ids=last_message_id) if last_message_id else None
        if current_message is None:
            LOGGER.warning("WenJianJi cannot resume; last page message was not found message_id=%s.", last_message_id)
            return {
                "sent_message_id": sent_message_id,
                "pages_seen": len(pages),
                "pages": pages,
                "stop_reason": "resume_page_not_found",
                "resumed": True,
            }

        return await _click_remaining_pages(
            client,
            entity,
            current_message=current_message,
            settings=settings,
            sent_message_id=sent_message_id,
            initial_pages=pages,
            resumed=True,
        )


async def _send_and_click_all_pages(target_bot: str, message: str, settings: CodeRouterAgentSettings) -> dict[str, Any]:
    async with build_telethon_client(settings) as client:
        if not await client.is_user_authorized():
            raise RuntimeError("Telethon session is not authorized. Log in once before enabling real sends.")

        entity = await client.get_entity(target_bot)
        sent_message = await client.send_message(entity, message)
        LOGGER.info("WenJianJi sent message_id=%s to %s; waiting for first page.", sent_message.id, target_bot)
        current_message = await _wait_for_latest_page_message(
            client,
            entity,
            after_id=sent_message.id,
            timeout_seconds=settings.wenjianji_page_wait_seconds,
            poll_interval_seconds=settings.wenjianji_poll_interval_seconds,
        )
        if current_message is None:
            LOGGER.warning("WenJianJi did not receive a page reply after sent_message_id=%s.", sent_message.id)
            return {
                "sent_message_id": sent_message.id,
                "pages_seen": 0,
                "pages": [],
                "stop_reason": "no_reply_after_send",
                "resumed": False,
            }

        return await _click_remaining_pages(
            client,
            entity,
            current_message=current_message,
            settings=settings,
            sent_message_id=sent_message.id,
            initial_pages=[],
            resumed=False,
        )


async def _click_remaining_pages(
    client,
    entity,
    *,
    current_message,
    settings: CodeRouterAgentSettings,
    sent_message_id: int,
    initial_pages: list[dict[str, Any]] | None = None,
    resumed: bool = False,
) -> dict[str, Any]:
    pages: list[dict[str, Any]] = list(initial_pages or [])
    seen_message_ids = {int(page.get("message_id")) for page in pages if page.get("message_id") is not None}
    stop_reason = "unknown"

    for _ in range(settings.wenjianji_max_pages):
        summary = _summarize_page(current_message)
        LOGGER.info(
            "WenJianJi page seen: message_id=%s current=%s total=%s has_next=%s resumed=%s.",
            summary.message_id,
            summary.current_page,
            summary.total_pages,
            summary.has_next_button,
            resumed,
        )
        if summary.message_id not in seen_message_ids:
            pages.append(asdict(summary))
            seen_message_ids.add(summary.message_id)

        if summary.current_page is not None and summary.total_pages is not None and summary.current_page >= summary.total_pages:
            stop_reason = "last_page_reached"
            LOGGER.info("WenJianJi reached last page at message_id=%s.", summary.message_id)
            break

        next_button = _find_next_page_button(current_message)
        if next_button is None:
            stop_reason = "next_button_not_found"
            LOGGER.info("WenJianJi next page button not found at message_id=%s.", summary.message_id)
            break

        expected_next_page = summary.current_page + 1 if summary.current_page is not None else None
        LOGGER.info(
            "WenJianJi clicking next button at message_id=%s row=%s col=%s expected_next_page=%s.",
            current_message.id,
            next_button[0],
            next_button[1],
            expected_next_page,
        )
        await current_message.click(*next_button)
        updated_message = await _wait_for_latest_page_message(
            client,
            entity,
            after_id=current_message.id,
            timeout_seconds=settings.wenjianji_page_wait_seconds,
            expected_current_page=expected_next_page,
            poll_interval_seconds=settings.wenjianji_poll_interval_seconds,
        )
        if updated_message is None:
            stop_reason = "no_page_update_after_click"
            LOGGER.warning("WenJianJi did not receive next page after clicking message_id=%s.", current_message.id)
            break
        current_message = updated_message
    else:
        stop_reason = "max_pages_reached"
        LOGGER.warning("WenJianJi reached max pages limit=%s.", settings.wenjianji_max_pages)

    return {
        "sent_message_id": sent_message_id,
        "pages_seen": len(pages),
        "pages": pages,
        "stop_reason": stop_reason,
        "resumed": resumed,
    }


async def _find_existing_page_message_after(client, entity, *, after_id: int, expected_current_page: int | None = None):
    messages = await client.get_messages(entity, limit=200)
    incoming = [message for message in messages if not message.out and message.id > after_id]
    return _find_page_message(incoming, expected_current_page=expected_current_page) if incoming else None

async def _wait_for_latest_page_message(client, entity, *, after_id: int, timeout_seconds: float, expected_current_page: int | None = None, poll_interval_seconds: float = 2):
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while True:
        messages = await client.get_messages(entity, limit=200)
        incoming = [message for message in messages if not message.out and message.id > after_id]
        if incoming:
            page_message = _find_page_message(incoming, expected_current_page=expected_current_page)
            if page_message is not None:
                return page_message
        if asyncio.get_running_loop().time() >= deadline:
            LOGGER.warning(
                "WenJianJi page wait timed out after_id=%s expected_current_page=%s incoming_count=%s timeout=%s.",
                after_id,
                expected_current_page,
                len(incoming),
                timeout_seconds,
            )
            return None
        await asyncio.sleep(poll_interval_seconds)


def _find_page_message(messages, *, expected_current_page: int | None = None):
    for message in messages:
        text = message.message or ""
        if _is_done_message(message):
            return message
        current_page, _ = _extract_page_numbers(text)
        is_page_message = current_page is not None or _find_next_page_button(message) is not None
        if not is_page_message:
            continue
        if expected_current_page is None:
            return message
        if current_page == expected_current_page:
            return message
    return None

def _is_done_message(message) -> bool:
    text = message.message or ""
    return any(marker in text for marker in DONE_MESSAGE_MARKERS)

def _summarize_page(message) -> PageSummary:
    text = message.message or ""
    current_page, total_pages = _extract_page_numbers(text)
    return PageSummary(
        message_id=int(message.id),
        text=text[:500],
        current_page=current_page,
        total_pages=total_pages,
        has_next_button=_find_next_page_button(message) is not None,
    )


def _extract_page_numbers(text: str) -> tuple[int | None, int | None]:
    match = PAGE_PATTERN.search(text)
    if match is None:
        return None, None
    return int(match.group("current")), int(match.group("total"))


def _find_next_page_button(message) -> tuple[int, int] | None:
    if not message.buttons:
        return None
    for row_index, row in enumerate(message.buttons):
        for col_index, button in enumerate(row):
            if NEXT_PAGE_BUTTON_TEXT in (button.text or ""):
                return row_index, col_index
    return None