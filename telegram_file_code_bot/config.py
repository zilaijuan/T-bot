from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True, slots=True)
class Settings:
    bot_token: str
    database_path: Path
    code_length: int

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()

        bot_token = os.getenv("BOT_TOKEN", "").strip()
        if not bot_token:
            raise RuntimeError("Missing BOT_TOKEN. Create a .env file first.")

        database_path = Path(os.getenv("DATABASE_PATH", "data/bot.db")).expanduser()

        raw_code_length = os.getenv("CODE_LENGTH", "8").strip()
        try:
            code_length = int(raw_code_length)
        except ValueError as exc:
            raise RuntimeError("CODE_LENGTH must be an integer.") from exc

        if code_length < 4:
            raise RuntimeError("CODE_LENGTH must be at least 4.")

        return cls(
            bot_token=bot_token,
            database_path=database_path,
            code_length=code_length,
        )
