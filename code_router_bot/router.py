from __future__ import annotations

import asyncio
import logging
from typing import Any

from telethon import TelegramClient, events, utils

from code_router_bot.config import PeerRef, Settings
from code_router_bot.parser import CodeParser


LOGGER = logging.getLogger(__name__)


class MessageRouter:
    def __init__(self, client: TelegramClient, settings: Settings) -> None:
        self.client = client
        self.settings = settings
        self.parser = CodeParser(settings.code_regex)
        self.forward_entity: Any | None = None
        self.forward_chat_id: int | None = None
        self.route_entities: dict[str, Any] = {}
        self.route_chat_ids: set[int] = set()
        self.route_locks: dict[str, asyncio.Lock] = {}

    async def start(self) -> None:
        self.forward_entity = await self.client.get_entity(self.settings.forward_chat)
        self.forward_chat_id = utils.get_peer_id(self.forward_entity)

        for prefix, target in self.settings.routes.items():
            entity = await self.client.get_entity(target)
            self.route_entities[prefix] = entity
            self.route_chat_ids.add(utils.get_peer_id(entity))
            lock_key = self.lock_key(target)
            if lock_key not in self.route_locks:
                self.route_locks[lock_key] = asyncio.Lock()

        chats_filter = self.settings.listen_chat_ids or None
        self.client.add_event_handler(
            self.handle_new_message,
            events.NewMessage(incoming=True, chats=chats_filter),
        )
        LOGGER.info("Router is listening for messages.")

    async def handle_new_message(self, event: events.NewMessage.Event) -> None:
        if self.forward_chat_id is not None and event.chat_id == self.forward_chat_id:
            return

        if event.chat_id in self.route_chat_ids:
            return

        sender = await event.get_sender()
        if getattr(sender, "bot", False):
            return

        text = event.raw_text or ""
        if not text.strip():
            return

        codes = self.parser.extract_codes(text)
        if not codes:
            return

        LOGGER.info("Found %s code(s) in message %s.", len(codes), event.id)
        for code in codes:
            await self.process_code(event, code)

    async def process_code(self, event: events.NewMessage.Event, code: str) -> None:
        prefix = self.parser.extract_prefix(code)
        if prefix is None:
            await self.send_notice(event, code, "No prefix could be extracted.")
            return

        target = self.settings.routes.get(prefix)
        if target is None:
            await self.send_notice(event, code, f"No route configured for prefix {prefix}.")
            return

        try:
            responses = await self.query_target_bot(prefix, target, code)
        except Exception as exc:
            LOGGER.exception("Failed to process code %s.", code)
            await self.send_notice(event, code, f"Request failed: {exc}")
            return

        if not responses:
            await self.send_notice(event, code, f"No response from {self.display_peer(target)}.")
            return

        await self.forward_responses(event, code, prefix, target, responses)

    async def query_target_bot(
        self,
        prefix: str,
        target: PeerRef,
        code: str,
    ) -> list[Any]:
        lock = self.route_locks[self.lock_key(target)]
        async with lock:
            async with self.client.conversation(
                entity=target,
                timeout=self.settings.request_timeout,
            ) as conversation:
                await conversation.send_message(code)

                responses: list[Any] = []
                first_response = await conversation.get_response(timeout=self.settings.request_timeout)
                if self.should_keep_message(first_response):
                    responses.append(first_response)

                while True:
                    try:
                        next_response = await conversation.get_response(
                            timeout=self.settings.response_idle_timeout
                        )
                    except asyncio.TimeoutError:
                        break

                    if self.should_keep_message(next_response):
                        responses.append(next_response)

        return responses

    async def forward_responses(
        self,
        event: events.NewMessage.Event,
        code: str,
        prefix: str,
        target: PeerRef,
        responses: list[Any],
    ) -> None:
        if self.forward_entity is None:
            raise RuntimeError("Forward chat is not initialized.")

        if self.settings.forward_summary:
            await self.client.send_message(
                self.forward_entity,
                self.build_summary(event, code, prefix, target, len(responses)),
            )

        await self.client.forward_messages(self.forward_entity, responses)

    async def send_notice(
        self,
        event: events.NewMessage.Event,
        code: str,
        details: str,
    ) -> None:
        if self.forward_entity is None:
            raise RuntimeError("Forward chat is not initialized.")

        origin_label = await self.describe_origin(event)
        await self.client.send_message(
            self.forward_entity,
            f"[router-notice]\norigin: {origin_label}\ncode: {code}\ndetails: {details}",
        )

    async def describe_origin(self, event: events.NewMessage.Event) -> str:
        chat = await event.get_chat()
        sender = await event.get_sender()

        chat_title = getattr(chat, "title", None) or getattr(chat, "username", None) or str(event.chat_id)
        sender_name = getattr(sender, "username", None)
        if sender_name:
            sender_label = f"@{sender_name}"
        else:
            first_name = getattr(sender, "first_name", None) or ""
            last_name = getattr(sender, "last_name", None) or ""
            sender_label = (first_name + " " + last_name).strip() or str(getattr(sender, "id", "unknown"))

        return f"{chat_title} / {sender_label} / message:{event.id}"

    async def build_summary(
        self,
        event: events.NewMessage.Event,
        code: str,
        prefix: str,
        target: PeerRef,
        response_count: int,
    ) -> str:
        origin_label = await self.describe_origin(event)
        return (
            "[router-summary]\n"
            f"origin: {origin_label}\n"
            f"code: {code}\n"
            f"prefix: {prefix}\n"
            f"target: {self.display_peer(target)}\n"
            f"response_count: {response_count}"
        )

    @staticmethod
    def should_keep_message(message: Any) -> bool:
        return not getattr(message, "action", None)

    @staticmethod
    def display_peer(peer: PeerRef) -> str:
        return str(peer)

    @staticmethod
    def lock_key(peer: PeerRef) -> str:
        return str(peer)
