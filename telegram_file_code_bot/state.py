from __future__ import annotations

from dataclasses import dataclass

from telegram_file_code_bot.config import Settings
from telegram_file_code_bot.database import Database


@dataclass(slots=True)
class RuntimeState:
    settings: Settings
    database: Database
    bot_username: str | None = None
