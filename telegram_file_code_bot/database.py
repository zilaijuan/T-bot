from __future__ import annotations

import secrets
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path


CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


@dataclass(frozen=True, slots=True)
class BundleItemInput:
    media_type: str
    storage_type: str
    telegram_file_id: str | None
    local_path: str | None
    caption: str | None
    file_name: str | None
    mime_type: str | None


@dataclass(frozen=True, slots=True)
class BundleItem:
    id: int
    bundle_code: str
    position: int
    media_type: str
    storage_type: str
    telegram_file_id: str | None
    local_path: str | None
    caption: str | None
    file_name: str | None
    mime_type: str | None
    created_at: str


@dataclass(frozen=True, slots=True)
class BundleRecord:
    code: str
    source: str
    uploader_id: int | None
    uploader_name: str | None
    created_at: str
    expires_at: str | None
    is_permanent: bool
    pickup_count: int
    last_accessed_at: str | None
    items: tuple[BundleItem, ...]

    def is_expired(self, reference_time: datetime | None = None) -> bool:
        if self.is_permanent or not self.expires_at:
            return False

        compare_at = reference_time or datetime.now(timezone.utc)
        return datetime.fromisoformat(self.expires_at) <= compare_at


@dataclass(frozen=True, slots=True)
class AdminStats:
    total_bundles: int
    total_items: int
    active_bundles: int
    expired_bundles: int
    permanent_bundles: int
    temporary_bundles: int
    telegram_bundles: int
    web_bundles: int
    total_pickups: int
    unique_uploaders: int
    recent_bundles_24h: int


class Database:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.database_path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.lock = threading.RLock()

    def init(self) -> None:
        with self.lock:
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS bundles (
                    code TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    uploader_id INTEGER,
                    uploader_name TEXT,
                    created_at TEXT NOT NULL,
                    expires_at TEXT,
                    is_permanent INTEGER NOT NULL DEFAULT 0,
                    pickup_count INTEGER NOT NULL DEFAULT 0,
                    last_accessed_at TEXT
                )
                """
            )
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS bundle_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bundle_code TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    media_type TEXT NOT NULL,
                    storage_type TEXT NOT NULL,
                    telegram_file_id TEXT,
                    local_path TEXT,
                    caption TEXT,
                    file_name TEXT,
                    mime_type TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(bundle_code) REFERENCES bundles(code) ON DELETE CASCADE
                )
                """
            )
            self.connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_bundle_items_bundle_code ON bundle_items(bundle_code, position)"
            )
            self.connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_bundles_expires_at ON bundles(expires_at)"
            )
            self.connection.commit()

    def create_bundle(
        self,
        *,
        items: list[BundleItemInput],
        source: str,
        uploader_id: int | None,
        uploader_name: str | None,
        is_permanent: bool,
        expires_at: str | None,
        code_length: int,
    ) -> BundleRecord:
        if not items:
            raise ValueError("Bundle must contain at least one item.")

        with self.lock:
            for _ in range(20):
                code = self._generate_code(code_length)
                created_at = datetime.now(timezone.utc).isoformat()

                try:
                    self.connection.execute("BEGIN")
                    self.connection.execute(
                        """
                        INSERT INTO bundles (
                            code,
                            source,
                            uploader_id,
                            uploader_name,
                            created_at,
                            expires_at,
                            is_permanent,
                            pickup_count,
                            last_accessed_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, NULL)
                        """,
                        (
                            code,
                            source,
                            uploader_id,
                            uploader_name,
                            created_at,
                            expires_at,
                            int(is_permanent),
                        ),
                    )

                    for position, item in enumerate(items, start=1):
                        self.connection.execute(
                            """
                            INSERT INTO bundle_items (
                                bundle_code,
                                position,
                                media_type,
                                storage_type,
                                telegram_file_id,
                                local_path,
                                caption,
                                file_name,
                                mime_type,
                                created_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                code,
                                position,
                                item.media_type,
                                item.storage_type,
                                item.telegram_file_id,
                                item.local_path,
                                item.caption,
                                item.file_name,
                                item.mime_type,
                                created_at,
                            ),
                        )

                    self.connection.commit()
                    bundle = self.get_bundle(code)
                    if bundle is None:
                        raise RuntimeError("Bundle was created but could not be loaded.")
                    return bundle
                except sqlite3.IntegrityError:
                    self.connection.rollback()
                    continue
                except Exception:
                    self.connection.rollback()
                    raise

        raise RuntimeError("Could not generate a unique pickup code.")

    def get_bundle(self, code: str) -> BundleRecord | None:
        with self.lock:
            bundle_row = self.connection.execute(
                """
                SELECT
                    code,
                    source,
                    uploader_id,
                    uploader_name,
                    created_at,
                    expires_at,
                    is_permanent,
                    pickup_count,
                    last_accessed_at
                FROM bundles
                WHERE code = ?
                """,
                (code,),
            ).fetchone()

            if bundle_row is None:
                return None

            item_rows = self.connection.execute(
                """
                SELECT
                    id,
                    bundle_code,
                    position,
                    media_type,
                    storage_type,
                    telegram_file_id,
                    local_path,
                    caption,
                    file_name,
                    mime_type,
                    created_at
                FROM bundle_items
                WHERE bundle_code = ?
                ORDER BY position ASC, id ASC
                """,
                (code,),
            ).fetchall()

        return BundleRecord(
            code=bundle_row["code"],
            source=bundle_row["source"],
            uploader_id=bundle_row["uploader_id"],
            uploader_name=bundle_row["uploader_name"],
            created_at=bundle_row["created_at"],
            expires_at=bundle_row["expires_at"],
            is_permanent=bool(bundle_row["is_permanent"]),
            pickup_count=bundle_row["pickup_count"],
            last_accessed_at=bundle_row["last_accessed_at"],
            items=tuple(
                BundleItem(
                    id=row["id"],
                    bundle_code=row["bundle_code"],
                    position=row["position"],
                    media_type=row["media_type"],
                    storage_type=row["storage_type"],
                    telegram_file_id=row["telegram_file_id"],
                    local_path=row["local_path"],
                    caption=row["caption"],
                    file_name=row["file_name"],
                    mime_type=row["mime_type"],
                    created_at=row["created_at"],
                )
                for row in item_rows
            ),
        )

    def mark_bundle_delivered(self, code: str) -> None:
        with self.lock:
            self.connection.execute(
                """
                UPDATE bundles
                SET pickup_count = pickup_count + 1,
                    last_accessed_at = ?
                WHERE code = ?
                """,
                (datetime.now(timezone.utc).isoformat(), code),
            )
            self.connection.commit()

    def get_admin_stats(self) -> AdminStats:
        now_iso = datetime.now(timezone.utc).isoformat()
        yesterday_iso = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()

        with self.lock:
            aggregates = self.connection.execute(
                """
                SELECT
                    COUNT(*) AS total_bundles,
                    COALESCE(SUM(CASE WHEN is_permanent = 1 THEN 1 ELSE 0 END), 0) AS permanent_bundles,
                    COALESCE(SUM(CASE WHEN is_permanent = 0 THEN 1 ELSE 0 END), 0) AS temporary_bundles,
                    COALESCE(SUM(CASE WHEN source = 'telegram' THEN 1 ELSE 0 END), 0) AS telegram_bundles,
                    COALESCE(SUM(CASE WHEN source = 'web' THEN 1 ELSE 0 END), 0) AS web_bundles,
                    COALESCE(SUM(pickup_count), 0) AS total_pickups,
                    COALESCE(SUM(CASE
                        WHEN is_permanent = 0 AND expires_at IS NOT NULL AND expires_at <= ? THEN 1
                        ELSE 0
                    END), 0) AS expired_bundles,
                    COALESCE(SUM(CASE
                        WHEN is_permanent = 1 OR expires_at IS NULL OR expires_at > ? THEN 1
                        ELSE 0
                    END), 0) AS active_bundles,
                    COALESCE(SUM(CASE WHEN created_at >= ? THEN 1 ELSE 0 END), 0) AS recent_bundles_24h
                FROM bundles
                """,
                (now_iso, now_iso, yesterday_iso),
            ).fetchone()

            total_items = self.connection.execute(
                "SELECT COUNT(*) AS total_items FROM bundle_items"
            ).fetchone()["total_items"]

            unique_uploaders = self.connection.execute(
                """
                SELECT COUNT(DISTINCT uploader_id) AS unique_uploaders
                FROM bundles
                WHERE uploader_id IS NOT NULL
                """
            ).fetchone()["unique_uploaders"]

        return AdminStats(
            total_bundles=aggregates["total_bundles"],
            total_items=total_items,
            active_bundles=aggregates["active_bundles"],
            expired_bundles=aggregates["expired_bundles"],
            permanent_bundles=aggregates["permanent_bundles"],
            temporary_bundles=aggregates["temporary_bundles"],
            telegram_bundles=aggregates["telegram_bundles"],
            web_bundles=aggregates["web_bundles"],
            total_pickups=aggregates["total_pickups"],
            unique_uploaders=unique_uploaders,
            recent_bundles_24h=aggregates["recent_bundles_24h"],
        )

    def close(self) -> None:
        with self.lock:
            self.connection.close()

    @staticmethod
    def _generate_code(code_length: int) -> str:
        return "".join(secrets.choice(CODE_ALPHABET) for _ in range(code_length))
