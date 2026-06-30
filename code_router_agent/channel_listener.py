from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from telethon import events
from telethon.utils import get_peer_id

from code_router_agent.channel_storage import ChannelMessageInput, ChannelMessageRepository, serialize_telethon_message
from code_router_agent.config import CodeRouterAgentSettings
from code_router_agent.telethon_client import build_telethon_client


LOGGER = logging.getLogger(__name__)


class ChannelMessageListener:
    def __init__(self, settings: CodeRouterAgentSettings, repository: ChannelMessageRepository | None = None) -> None:
        self.settings = settings
        self.repository = repository or ChannelMessageRepository(settings.database_path)
        self.repository.init()

    async def run_forever(self, stop_event: asyncio.Event) -> None:
        channel = self.settings.channel_listener_channel
        async with build_telethon_client(self.settings) as client:
            if not await client.is_user_authorized():
                raise RuntimeError("Telethon session is not authorized. Log in once before enabling channel listener.")

            entity = await client.get_entity(_parse_channel_reference(channel))
            channel_id = get_peer_id(entity)
            username = getattr(entity, "username", None)
            LOGGER.info(
                "code_router_agent channel listener started for channel=%s id=%s username=%s.",
                channel,
                channel_id,
                username,
            )
            await self._sync_history(client, entity, channel_id=int(channel_id), username=username, stop_event=stop_event)

            @client.on(events.NewMessage(chats=entity))
            async def on_new_message(event):
                self._save_message(
                    message=event.message,
                    channel_id=int(event.chat_id or channel_id),
                    username=username,
                    log_prefix="Saved channel message",
                )

            while not stop_event.is_set():
                await asyncio.sleep(1)

            await client.disconnect()
            LOGGER.info("code_router_agent channel listener stopped for channel=%s.", channel)

    async def _sync_history(self, client, entity, *, channel_id: int, username: str | None, stop_event: asyncio.Event) -> None:
        saved_count = 0
        skipped_count = 0
        LOGGER.info("Syncing channel history channel_id=%s username=%s.", channel_id, username)
        async for message in client.iter_messages(entity, reverse=True):
            if stop_event.is_set():
                break
            saved = self._save_message(
                message=message,
                channel_id=channel_id,
                username=username,
                log_prefix="Saved historical channel message",
            )
            if saved:
                saved_count += 1
            else:
                skipped_count += 1
        LOGGER.info(
            "Channel history sync finished channel_id=%s saved=%s skipped_existing=%s.",
            channel_id,
            saved_count,
            skipped_count,
        )

    def _save_message(self, *, message, channel_id: int, username: str | None, log_prefix: str) -> bool:
        text = message.raw_text or ""
        saved = self.repository.save_message(
            ChannelMessageInput(
                channel_id=channel_id,
                channel_username=username,
                message_id=int(message.id),
                sender_id=_optional_int(getattr(message, "sender_id", None)),
                message_date=_optional_datetime(getattr(message, "date", None)),
                text=text,
                raw_message_json=serialize_telethon_message(message),
            )
        )
        if saved:
            LOGGER.info(
                "%s channel_id=%s message_id=%s text_length=%s.",
                log_prefix,
                channel_id,
                message.id,
                len(text),
            )
        else:
            LOGGER.debug(
                "Skipped duplicate channel message channel_id=%s message_id=%s.",
                channel_id,
                message.id,
            )
        return saved


async def resolve_channel_id(settings: CodeRouterAgentSettings) -> int:
    async with build_telethon_client(settings) as client:
        if not await client.is_user_authorized():
            raise RuntimeError("Telethon session is not authorized. Log in once before resolving channel id.")
        entity = await client.get_entity(_parse_channel_reference(settings.channel_listener_channel))
        return int(get_peer_id(entity))


def _parse_channel_reference(value: str) -> str | int:
    stripped = value.strip()
    if stripped.lstrip("-").isdigit():
        return int(stripped)
    return stripped


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_datetime(value: object) -> datetime | None:
    return value if isinstance(value, datetime) else None
