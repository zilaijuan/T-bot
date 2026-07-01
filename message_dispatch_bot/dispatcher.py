from __future__ import annotations

import logging

from telegram import Bot
from telegram.error import Forbidden, TelegramError

from message_dispatch_bot.config import MessageDispatchSettings
from message_dispatch_bot.storage import (
    OUTPUT_TASK_DONE,
    OUTPUT_TASK_FAILED,
    OUTPUT_TASK_NEW,
    SUBSCRIBER_BLOCKED,
    DispatchPayload,
    MessageDispatchRepository,
    SubscriberRecord,
)


LOGGER = logging.getLogger(__name__)
TELEGRAM_MESSAGE_LIMIT = 4096
SAFE_MESSAGE_LIMIT = 3900


class MessageDispatcher:
    def __init__(self, settings: MessageDispatchSettings, repository: MessageDispatchRepository) -> None:
        self.settings = settings
        self.repository = repository

    async def run_once(self, bot: Bot) -> int:
        processed = 0
        for _ in range(self.settings.max_tasks_per_run):
            task_id = self.repository.claim_next_output_task()
            if task_id is None:
                break
            processed += 1
            await self._dispatch_task(bot, task_id)
        return processed

    async def _dispatch_task(self, bot: Bot, task_id: int) -> None:
        subscribers = self.repository.list_active_subscribers()
        if not subscribers:
            LOGGER.info("No active message dispatch subscribers; task_id=%s returned to NEW.", task_id)
            self.repository.update_output_task_status(task_id, OUTPUT_TASK_NEW)
            return

        payload = self.repository.get_payload(task_id)
        if payload is None:
            LOGGER.warning("Message dispatch payload not found for task_id=%s; marking FAILED.", task_id)
            self.repository.update_output_task_status(task_id, OUTPUT_TASK_FAILED)
            return

        try:
            for subscriber in subscribers:
                await self._send_payload_to_subscriber(bot, payload, subscriber)
        except Exception:
            LOGGER.exception("Message dispatch task_id=%s failed; returning to NEW.", task_id)
            self.repository.update_output_task_status(task_id, OUTPUT_TASK_NEW)
            return

        self.repository.update_output_task_status(task_id, OUTPUT_TASK_DONE)
        LOGGER.info(
            "Message dispatch task_id=%s done; subscribers=%s output_messages=%s.",
            task_id,
            len(subscribers),
            len(payload.output_messages),
        )

    async def _send_payload_to_subscriber(self, bot: Bot, payload: DispatchPayload, subscriber: SubscriberRecord) -> None:
        try:
            if payload.original_text:
                await _send_text(bot, subscriber.chat_id, payload.original_text)
            for output_message in payload.output_messages:
                if output_message.content:
                    await _send_text(bot, subscriber.chat_id, output_message.content)
        except Forbidden:
            LOGGER.info(
                "Message dispatch subscriber user_id=%s chat_id=%s is blocked/inaccessible.",
                subscriber.user_id,
                subscriber.chat_id,
            )
            self.repository.update_subscriber_status(subscriber.user_id, SUBSCRIBER_BLOCKED)
        except TelegramError:
            LOGGER.exception(
                "Failed to dispatch task_id=%s to subscriber user_id=%s chat_id=%s.",
                payload.task_id,
                subscriber.user_id,
                subscriber.chat_id,
            )


async def _send_text(bot: Bot, chat_id: int, text: str) -> None:
    for chunk in _split_text(text):
        await bot.send_message(chat_id=chat_id, text=chunk)


def _split_text(text: str) -> tuple[str, ...]:
    if len(text) <= TELEGRAM_MESSAGE_LIMIT:
        return (text,)
    chunks: list[str] = []
    remaining = text
    while remaining:
        chunk = remaining[:SAFE_MESSAGE_LIMIT]
        split_at = max(chunk.rfind("\n"), chunk.rfind(" "))
        if split_at > 0:
            chunk = chunk[:split_at]
        chunks.append(chunk)
        remaining = remaining[len(chunk):].lstrip()
    return tuple(chunks)
