from __future__ import annotations

import asyncio
import contextlib
import logging
import os

from dotenv import load_dotenv
from telegram.ext import Application

from backup_bot.config import BackupSettings
from backup_bot.main import build_application as build_backup_bot
from code_collector_bot.config import CodeCollectorSettings
from code_collector_bot.main import build_application as build_code_collector_bot
from code_router_agent.agent import CodeRouterAgent
from code_router_agent.config import CodeRouterAgentSettings
from message_dispatch_bot.config import MessageDispatchSettings
from message_dispatch_bot.main import build_application as build_message_dispatch_bot
from telegram_file_code_bot.app.logging import configure_logging
from telegram_file_code_bot.app.main import build_application as build_file_code_bot
from tg_msg_collector_bot.main import build_application as build_msg_collector_bot
from tg_msg_collector_bot.main import configure_logging as configure_msg_collector_logging


LOGGER = logging.getLogger(__name__)


def _env_enabled(name: str, *, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


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
    load_dotenv()
    configure_logging()

    file_code_enabled = _env_enabled("TELEGRAM_FILE_CODE_BOT_ENABLED", default=True)
    msg_collector_enabled = _env_enabled(
        "TG_MSG_COLLECTOR_BOT_ENABLED",
        default=_env_enabled("TG_MSG_COLLECTOR_ENABLED", default=True),
    )
    backup_settings = BackupSettings.from_env()
    code_collector_bot_settings = CodeCollectorSettings.from_env()
    code_router_agent_settings = CodeRouterAgentSettings.from_env()
    message_dispatch_settings = MessageDispatchSettings.from_env()

    applications: list[tuple[str, Application]] = []
    agent_instances: list[tuple[str, CodeRouterAgent]] = []

    if file_code_enabled:
        applications.append(("telegram_file_code_bot", build_file_code_bot()))
    else:
        LOGGER.info("telegram_file_code_bot is disabled. Set TELEGRAM_FILE_CODE_BOT_ENABLED=true to start it.")

    if msg_collector_enabled:
        configure_msg_collector_logging()
        applications.append(("tg_msg_collector_bot", build_msg_collector_bot()))
    else:
        LOGGER.info("tg_msg_collector_bot is disabled. Set TG_MSG_COLLECTOR_BOT_ENABLED=true to start it.")

    if code_collector_bot_settings.enabled:
        applications.append(("code_collector_bot", build_code_collector_bot(code_collector_bot_settings)))
    else:
        LOGGER.info("code_collector_bot is disabled. Set CODE_COLLECTOR_BOT_ENABLED=true to start it.")

    if code_router_agent_settings.enabled:
        agent_instances.append(("code_router_agent", CodeRouterAgent(code_router_agent_settings)))
    else:
        LOGGER.info("code_router_agent is disabled. Set CODE_ROUTER_AGENT_ENABLED=true to start it.")

    if backup_settings.enabled:
        applications.append(("backup_bot", build_backup_bot(backup_settings)))
    else:
        LOGGER.info("backup_bot is disabled. Set BACKUP_BOT_ENABLED=true to start it.")

    if message_dispatch_settings.enabled:
        applications.append(("message_dispatch_bot", build_message_dispatch_bot(message_dispatch_settings)))
    else:
        LOGGER.info("message_dispatch_bot is disabled. Set MESSAGE_DISPATCH_BOT_ENABLED=true to start it.")

    started: list[tuple[str, Application]] = []
    started_agents: list[tuple[str, CodeRouterAgent, asyncio.Task[None]]] = []
    try:
        for name, application in applications:
            await _start_application(name, application)
            started.append((name, application))

        for name, agent in agent_instances:
            task = asyncio.create_task(agent.run_forever(), name=name)
            started_agents.append((name, agent, task))

        LOGGER.info("All bots and agents are running. Press Ctrl+C to stop.")
        await asyncio.Event().wait()
    finally:
        for name, agent, task in reversed(started_agents):
            LOGGER.info("Stopping %s...", name)
            agent.stop()
            with contextlib.suppress(Exception):
                await task

        for name, application in reversed(started):
            with contextlib.suppress(Exception):
                await _stop_application(name, application)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass