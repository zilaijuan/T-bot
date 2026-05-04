from __future__ import annotations

import asyncio
import logging

from telethon import TelegramClient
from telethon.sessions import StringSession

from code_router_bot.config import Settings
from code_router_bot.router import MessageRouter


def main() -> None:
    asyncio.run(run())


async def run() -> None:
    settings = Settings.from_env()
    configure_logging(settings.log_level)

    client = build_client(settings)
    await start_client(client, settings)

    router = MessageRouter(client, settings)
    await router.start()

    logging.getLogger(__name__).info("Client started. Waiting for messages.")
    await client.run_until_disconnected()


def build_client(settings: Settings) -> TelegramClient:
    if settings.string_session:
        session = StringSession(settings.string_session)
        return TelegramClient(session, settings.api_id, settings.api_hash)

    session_path = settings.session_path()
    session_path.parent.mkdir(parents=True, exist_ok=True)
    return TelegramClient(str(session_path), settings.api_id, settings.api_hash)


async def start_client(client: TelegramClient, settings: Settings) -> None:
    await client.start(
        phone=settings.phone_number,
        password=settings.two_fa_password,
    )


def configure_logging(level_name: str) -> None:
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
