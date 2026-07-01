from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote, urlparse

from code_router_agent.config import CodeRouterAgentSettings


def parse_telethon_proxy(proxy_url: str | None):
    if not proxy_url:
        return None

    try:
        import socks
    except ImportError as exc:
        raise RuntimeError("PySocks is required when TELETHON_PROXY_URL or TELEGRAM_PROXY_URL is configured.") from exc

    parsed = urlparse(proxy_url)
    scheme = parsed.scheme.lower()
    proxy_types = {
        "socks5": socks.SOCKS5,
        "socks5h": socks.SOCKS5,
        "socks4": socks.SOCKS4,
        "socks4a": socks.SOCKS4,
        "http": socks.HTTP,
    }
    proxy_type = proxy_types.get(scheme)
    if proxy_type is None:
        raise RuntimeError("TELETHON_PROXY_URL must use socks5://, socks5h://, socks4://, socks4a://, or http://.")
    if not parsed.hostname or parsed.port is None:
        raise RuntimeError("TELETHON_PROXY_URL must include host and port.")

    rdns = scheme in {"socks5h", "socks4a"}
    username = unquote(parsed.username) if parsed.username else None
    password = unquote(parsed.password) if parsed.password else None
    return (proxy_type, parsed.hostname, parsed.port, rdns, username, password)


def build_telethon_client(settings: CodeRouterAgentSettings, *, session_path: str | None = None):
    if settings.telethon_api_id is None or not settings.telethon_api_hash:
        raise RuntimeError("TELETHON_API_ID and TELETHON_API_HASH are required.")

    try:
        from telethon import TelegramClient
    except ImportError as exc:
        raise RuntimeError("telethon is required when a driver sends messages with Telethon.") from exc

    session_path_obj = Path(session_path or settings.telethon_session).expanduser()
    session_path_obj.parent.mkdir(parents=True, exist_ok=True)
    return TelegramClient(
        str(session_path_obj),
        settings.telethon_api_id,
        settings.telethon_api_hash,
        proxy=parse_telethon_proxy(settings.telethon_proxy_url),
        connection_retries=1,
        retry_delay=1,
        timeout=settings.telethon_timeout_seconds,
    )


async def send_messages_with_telethon(target_bot: str, messages: tuple[str, ...], settings: CodeRouterAgentSettings) -> None:
    async with build_telethon_client(settings) as client:
        if not await client.is_user_authorized():
            raise RuntimeError("Telethon session is not authorized. Log in once before enabling real sends.")
        for message in messages:
            await client.send_message(target_bot, message)