from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum


class ContentType(StrEnum):
    TEXT = "text"
    PHOTO = "photo"
    VIDEO = "video"
    DOCUMENT = "document"
    AUDIO = "audio"
    VOICE = "voice"


class BundleStatus(StrEnum):
    ACTIVE = "active"
    DELETED = "deleted"


@dataclass(frozen=True, slots=True)
class BundleItemInput:
    type: ContentType
    telegram_file_id: str | None = None
    local_path: str | None = None
    text: str | None = None
    caption: str | None = None
    file_name: str | None = None
    mime_type: str | None = None
    size: int | None = None
    metadata_json: str | None = None


@dataclass(frozen=True, slots=True)
class BundleItem:
    id: int
    bundle_code: str
    position: int
    type: ContentType
    telegram_file_id: str | None
    local_path: str | None
    text: str | None
    caption: str | None
    file_name: str | None
    mime_type: str | None
    size: int | None
    metadata_json: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Bundle:
    code: str
    owner_user_id: int
    owner_name: str | None
    description: str | None
    visibility: str
    created_at: datetime
    expires_at: datetime | None
    max_downloads: int | None
    download_count: int
    status: BundleStatus
    items: tuple[BundleItem, ...]

    def is_expired(self, now: datetime | None = None) -> bool:
        if self.expires_at is None:
            return False
        return self.expires_at <= (now or datetime.now(timezone.utc))

    def is_download_exhausted(self) -> bool:
        return self.max_downloads is not None and self.download_count >= self.max_downloads


@dataclass(slots=True)
class DraftBundle:
    user_id: int
    owner_name: str | None
    description: str | None
    expiry_spec: str
    items: list[BundleItemInput] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class AdminStats:
    total_bundles: int
    active_bundles: int
    deleted_bundles: int
    expired_bundles: int
    total_items: int
    total_downloads: int
    recent_bundles_24h: int
