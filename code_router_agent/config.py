from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True, slots=True)
class CodeRouterAgentSettings:
    enabled: bool
    database_url: str
    database_path: Path
    poll_interval_seconds: float
    idle_sleep_seconds: float
    qq_coder_target_bot: str | None
    qq_coder_dry_run: bool
    zyxfids_target_bot: str | None
    zyxfids_dry_run: bool
    amumu_jiema_target_bot: str | None
    amumu_jiema_dry_run: bool
    wenjianji_target_bot: str | None
    wenjianji_dry_run: bool
    wenjianji_page_wait_seconds: float
    wenjianji_poll_interval_seconds: float
    wenjianji_max_pages: int
    telethon_api_id: int | None
    telethon_api_hash: str | None
    telethon_session: str
    telethon_proxy_url: str | None
    telethon_timeout_seconds: float
    channel_listener_enabled: bool
    channel_listener_channel: str

    @classmethod
    def from_env(cls) -> "CodeRouterAgentSettings":
        load_dotenv()

        database_url = os.getenv("DATABASE_URL", "sqlite:///data/bots.db").strip() or "sqlite:///data/bots.db"
        return cls(
            enabled=_parse_bool(os.getenv("CODE_ROUTER_AGENT_ENABLED"), default=False),
            database_url=database_url,
            database_path=_sqlite_path_from_url(database_url),
            poll_interval_seconds=_parse_positive_float(
                os.getenv("CODE_ROUTER_AGENT_POLL_INTERVAL_SECONDS", "2"),
                name="CODE_ROUTER_AGENT_POLL_INTERVAL_SECONDS",
            ),
            idle_sleep_seconds=_parse_positive_float(
                os.getenv("CODE_ROUTER_AGENT_IDLE_SLEEP_SECONDS", "5"),
                name="CODE_ROUTER_AGENT_IDLE_SLEEP_SECONDS",
            ),
            qq_coder_target_bot=os.getenv("QQ_CODER_DRIVER_TARGET_BOT", "").strip() or None,
            qq_coder_dry_run=_parse_bool(os.getenv("QQ_CODER_DRIVER_DRY_RUN"), default=True),
            zyxfids_target_bot=os.getenv("ZYXFIDS_DRIVER_TARGET_BOT", "@zyxfids_bot").strip() or None,
            zyxfids_dry_run=_parse_bool(os.getenv("ZYXFIDS_DRIVER_DRY_RUN"), default=True),
            amumu_jiema_target_bot=os.getenv("AMUMU_JIEMA_DRIVER_TARGET_BOT", "@amumujiemabot").strip() or None,
            amumu_jiema_dry_run=_parse_bool(os.getenv("AMUMU_JIEMA_DRIVER_DRY_RUN"), default=True),
            wenjianji_target_bot=os.getenv("WENJIANJI_DRIVER_TARGET_BOT", "@WenJianJibot").strip() or None,
            wenjianji_dry_run=_parse_bool(os.getenv("WENJIANJI_DRIVER_DRY_RUN"), default=True),
            wenjianji_page_wait_seconds=_parse_positive_float(
                os.getenv("WENJIANJI_DRIVER_PAGE_WAIT_SECONDS", "60"),
                name="WENJIANJI_DRIVER_PAGE_WAIT_SECONDS",
            ),
            wenjianji_poll_interval_seconds=_parse_positive_float(
                os.getenv("WENJIANJI_DRIVER_POLL_INTERVAL_SECONDS", "2"),
                name="WENJIANJI_DRIVER_POLL_INTERVAL_SECONDS",
            ),
            wenjianji_max_pages=_parse_positive_int(
                os.getenv("WENJIANJI_DRIVER_MAX_PAGES", "50"),
                name="WENJIANJI_DRIVER_MAX_PAGES",
            ),
            telethon_api_id=_parse_optional_int(os.getenv("TELETHON_API_ID"), name="TELETHON_API_ID"),
            telethon_api_hash=os.getenv("TELETHON_API_HASH", "").strip() or None,
            telethon_session=os.getenv("TELETHON_SESSION", "data/telethon_user.session").strip() or "data/telethon_user.session",
            telethon_proxy_url=(
                os.getenv("TELETHON_PROXY_URL", "").strip()
                or os.getenv("TELEGRAM_PROXY_URL", "").strip()
                or os.getenv("PROXY_URL", "").strip()
                or None
            ),
            telethon_timeout_seconds=_parse_positive_float(
                os.getenv("TELETHON_TIMEOUT_SECONDS", "30"),
                name="TELETHON_TIMEOUT_SECONDS",
            ),
            channel_listener_enabled=_parse_bool(
                os.getenv("CODE_ROUTER_AGENT_CHANNEL_LISTENER_ENABLED"),
                default=False,
            ),
            channel_listener_channel=os.getenv("CODE_ROUTER_AGENT_CHANNEL_LISTENER_CHANNEL", "a260621").strip() or "a260621",
        )

    def validate(self) -> None:
        needs_telethon = (
            (not self.qq_coder_dry_run)
            or (not self.zyxfids_dry_run)
            or (not self.amumu_jiema_dry_run)
            or (not self.wenjianji_dry_run)
            or self.channel_listener_enabled
        )
        if not self.qq_coder_dry_run and not self.qq_coder_target_bot:
            raise RuntimeError("QQ_CODER_DRIVER_TARGET_BOT is required when QQ_CODER_DRIVER_DRY_RUN=false.")
        if not self.zyxfids_dry_run and not self.zyxfids_target_bot:
            raise RuntimeError("ZYXFIDS_DRIVER_TARGET_BOT is required when ZYXFIDS_DRIVER_DRY_RUN=false.")
        if not self.amumu_jiema_dry_run and not self.amumu_jiema_target_bot:
            raise RuntimeError("AMUMU_JIEMA_DRIVER_TARGET_BOT is required when AMUMU_JIEMA_DRIVER_DRY_RUN=false.")
        if not self.wenjianji_dry_run and not self.wenjianji_target_bot:
            raise RuntimeError("WENJIANJI_DRIVER_TARGET_BOT is required when WENJIANJI_DRIVER_DRY_RUN=false.")
        if self.channel_listener_enabled and not self.channel_listener_channel:
            raise RuntimeError("CODE_ROUTER_AGENT_CHANNEL_LISTENER_CHANNEL is required when channel listener is enabled.")
        if needs_telethon and (self.telethon_api_id is None or not self.telethon_api_hash):
            raise RuntimeError("TELETHON_API_ID and TELETHON_API_HASH are required when a Telethon driver dry-run is disabled.")


def _sqlite_path_from_url(database_url: str) -> Path:
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        raise RuntimeError("Only sqlite:/// DATABASE_URL is supported by code_router_agent.")
    raw_path = database_url[len(prefix) :]
    if not raw_path:
        raise RuntimeError("DATABASE_URL must include a SQLite database path.")
    return Path(raw_path).expanduser()


def _parse_bool(raw_value: str | None, *, default: bool) -> bool:
    if raw_value is None:
        return default
    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _parse_positive_float(raw_value: str | None, *, name: str) -> float:
    try:
        value = float((raw_value or "").strip())
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a number.") from exc
    if value <= 0:
        raise RuntimeError(f"{name} must be greater than 0.")
    return value


def _parse_positive_int(raw_value: str | None, *, name: str) -> int:
    try:
        value = int((raw_value or "").strip())
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer.") from exc
    if value <= 0:
        raise RuntimeError(f"{name} must be greater than 0.")
    return value


def _parse_optional_int(raw_value: str | None, *, name: str) -> int | None:
    if raw_value is None or not raw_value.strip():
        return None
    try:
        return int(raw_value.strip())
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer.") from exc