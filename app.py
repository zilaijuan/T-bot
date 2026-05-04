from __future__ import annotations

import asyncio
import contextlib
import logging

from telegram.ext import Application

from telegram_file_code_bot.app.logging import configure_logging
from telegram_file_code_bot.app.main import build_application as build_file_code_bot
from tg_msg_collector.main import build_application as build_msg_collector_bot
from tg_msg_collector.main import configure_logging as configure_msg_collector_logging


LOGGER = logging.getLogger(__name__)


async def _start_application(name: str, application: Application) -> None:
    await application.initialize()
    post_init = getattr(application, "post_init", None)
    if post_init is not None:
        await post_init(application)
    await application.start()
    if application.updater is None:
        raise RuntimeError(f"{name} does not have an updater.")
    await application.updater.start_polling()
    LOGGER.info("%s started.", name)


async def _stop_application(name: str, application: Application) -> None:
    LOGGER.info("Stopping %s...", name)
    if application.updater is not None and application.updater.running:
        await application.updater.stop()
    if application.running:
        await application.stop()
    await application.shutdown()
    LOGGER.info("%s stopped.", name)


async def main() -> None:
    configure_logging()
    configure_msg_collector_logging()

    applications: list[tuple[str, Application]] = [
        ("telegram_file_code_bot", build_file_code_bot()),
        ("tg_msg_collector", build_msg_collector_bot()),
    ]

    started: list[tuple[str, Application]] = []
    try:
        for name, application in applications:
            await _start_application(name, application)
            started.append((name, application))

        LOGGER.info("All bots are running. Press Ctrl+C to stop.")
        await asyncio.Event().wait()
    finally:
        for name, application in reversed(started):
            with contextlib.suppress(Exception):
                await _stop_application(name, application)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
