from __future__ import annotations

import asyncio

from code_router_agent.agent import CodeRouterAgent
from code_router_agent.config import CodeRouterAgentSettings
from telegram_file_code_bot.app.logging import configure_logging


def build_agent(settings: CodeRouterAgentSettings | None = None) -> CodeRouterAgent:
    settings = settings or CodeRouterAgentSettings.from_env()
    return CodeRouterAgent(settings)


def run() -> None:
    configure_logging()
    agent = build_agent()
    asyncio.run(agent.run_forever())


if __name__ == "__main__":
    run()