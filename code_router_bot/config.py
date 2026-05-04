from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias

from dotenv import load_dotenv


PeerRef: TypeAlias = str | int


@dataclass(frozen=True, slots=True)
class Settings:
    api_id: int
    api_hash: str
    phone_number: str | None
    two_fa_password: str | None
    string_session: str | None
    session_name: str
    listen_chat_ids: tuple[PeerRef, ...]
    forward_chat: PeerRef
    routes: dict[str, PeerRef]
    code_regex: str
    request_timeout: int
    response_idle_timeout: int
    forward_summary: bool
    log_level: str

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()

        api_id = _parse_required_int("API_ID")
        api_hash = _parse_required_string("API_HASH")
        phone_number = _parse_optional_string("PHONE_NUMBER")
        two_fa_password = _parse_optional_string("TWO_FA_PASSWORD")
        string_session = _parse_optional_string("STRING_SESSION")
        session_name = os.getenv("SESSION_NAME", "data/router_session").strip() or "data/router_session"
        listen_chat_ids = _parse_peer_list(os.getenv("LISTEN_CHAT_IDS", ""))
        forward_chat = _parse_peer(_parse_required_string("FORWARD_CHAT"))
        routes = _parse_routes(os.getenv("ROUTES_JSON", ""))
        code_regex = os.getenv(
            "CODE_REGEX",
            r"\b([A-Za-z]{1,10}(?:[-_:|][A-Za-z0-9]{4,64}|[A-Za-z0-9]{4,64}\d[A-Za-z0-9]{0,64}))\b",
        ).strip()
        request_timeout = _parse_int("REQUEST_TIMEOUT", 90)
        response_idle_timeout = _parse_int("RESPONSE_IDLE_TIMEOUT", 5)
        forward_summary = _parse_bool("FORWARD_SUMMARY", True)
        log_level = os.getenv("LOG_LEVEL", "INFO").strip().upper() or "INFO"

        if not string_session and not phone_number:
            raise RuntimeError("Set PHONE_NUMBER or STRING_SESSION.")

        if not routes:
            raise RuntimeError("ROUTES_JSON cannot be empty.")

        return cls(
            api_id=api_id,
            api_hash=api_hash,
            phone_number=phone_number,
            two_fa_password=two_fa_password,
            string_session=string_session,
            session_name=session_name,
            listen_chat_ids=listen_chat_ids,
            forward_chat=forward_chat,
            routes=routes,
            code_regex=code_regex,
            request_timeout=request_timeout,
            response_idle_timeout=response_idle_timeout,
            forward_summary=forward_summary,
            log_level=log_level,
        )

    def session_path(self) -> Path:
        return Path(self.session_name).expanduser()


def _parse_required_string(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing {name}.")
    return value


def _parse_optional_string(name: str) -> str | None:
    value = os.getenv(name, "").strip()
    return value or None


def _parse_required_int(name: str) -> int:
    return _parse_int(name, None)


def _parse_int(name: str, default: int | None) -> int:
    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        if default is None:
            raise RuntimeError(f"Missing {name}.")
        return default

    try:
        return int(raw_value.strip())
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer.") from exc


def _parse_bool(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default

    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _parse_routes(raw_value: str) -> dict[str, PeerRef]:
    if not raw_value.strip():
        return {}

    try:
        loaded = json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise RuntimeError("ROUTES_JSON must be valid JSON.") from exc

    if not isinstance(loaded, dict):
        raise RuntimeError("ROUTES_JSON must be a JSON object.")

    routes: dict[str, PeerRef] = {}
    for prefix, target in loaded.items():
        if not isinstance(prefix, str) or not prefix.strip():
            raise RuntimeError("Route prefixes must be non-empty strings.")
        routes[prefix.strip().upper()] = _parse_peer(str(target))
    return routes


def _parse_peer_list(raw_value: str) -> tuple[PeerRef, ...]:
    if not raw_value.strip():
        return ()
    return tuple(_parse_peer(part) for part in raw_value.split(",") if part.strip())


def _parse_peer(raw_value: str) -> PeerRef:
    stripped = raw_value.strip()
    if not stripped:
        raise RuntimeError("Peer value cannot be empty.")
    if stripped.lstrip("-").isdigit():
        return int(stripped)
    return stripped
