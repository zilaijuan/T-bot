from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


EXPIRY_PATTERN = re.compile(r"^(\d+)(m|h|d|w)$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class ExpiryPolicy:
    raw_spec: str
    expires_at: datetime | None


def parse_expiry_spec(raw_spec: str, default_spec: str) -> ExpiryPolicy:
    spec = (raw_spec or default_spec).strip().lower()
    if not spec:
        spec = default_spec.strip().lower()

    if spec in {"forever", "permanent", "never", "none"}:
        return ExpiryPolicy(raw_spec=spec, expires_at=None)

    match = EXPIRY_PATTERN.match(spec)
    if not match:
        raise ValueError("有效期格式不正确。示例：30m、12h、7d、4w、forever。")

    amount = int(match.group(1))
    unit = match.group(2).lower()
    if amount <= 0:
        raise ValueError("有效期必须大于 0。")

    delta_by_unit = {
        "m": timedelta(minutes=amount),
        "h": timedelta(hours=amount),
        "d": timedelta(days=amount),
        "w": timedelta(weeks=amount),
    }
    return ExpiryPolicy(raw_spec=spec, expires_at=datetime.now(timezone.utc) + delta_by_unit[unit])


def format_expiry(expires_at: datetime | None) -> str:
    if expires_at is None:
        return "永久有效"
    return expires_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
