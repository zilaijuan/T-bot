from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from telegram_file_code_bot.core.models import (
    AdminStats,
    Bundle,
    BundleItem,
    BundleItemInput,
    BundleStatus,
    ContentType,
)


class SQLiteBundleRepository:
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
                    owner_user_id INTEGER NOT NULL,
                    owner_name TEXT,
                    description TEXT,
                    visibility TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT,
                    max_downloads INTEGER,
                    download_count INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL
                )
                """
            )
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS bundle_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bundle_code TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    type TEXT NOT NULL,
                    telegram_file_id TEXT,
                    local_path TEXT,
                    text TEXT,
                    caption TEXT,
                    file_name TEXT,
                    mime_type TEXT,
                    size INTEGER,
                    metadata_json TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(bundle_code) REFERENCES bundles(code) ON DELETE CASCADE
                )
                """
            )
            self.connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_bundle_items_code_position ON bundle_items(bundle_code, position)"
            )
            self.connection.execute("CREATE INDEX IF NOT EXISTS idx_bundles_created_at ON bundles(created_at)")
            self.connection.execute("CREATE INDEX IF NOT EXISTS idx_bundles_expires_at ON bundles(expires_at)")
            self.connection.commit()

    def code_exists(self, code: str) -> bool:
        with self.lock:
            row = self.connection.execute("SELECT 1 FROM bundles WHERE code = ?", (code,)).fetchone()
            return row is not None

    def create_bundle(
        self,
        *,
        code: str,
        owner_user_id: int,
        owner_name: str | None,
        description: str | None,
        visibility: str,
        expires_at: datetime | None,
        max_downloads: int | None,
        items: list[BundleItemInput],
    ) -> Bundle:
        if not items:
            raise ValueError("Bundle must contain at least one item.")

        created_at = datetime.now(timezone.utc)
        with self.lock:
            self.connection.execute("BEGIN")
            try:
                self.connection.execute(
                    """
                    INSERT INTO bundles (
                        code,
                        owner_user_id,
                        owner_name,
                        description,
                        visibility,
                        created_at,
                        expires_at,
                        max_downloads,
                        download_count,
                        status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                    """,
                    (
                        code,
                        owner_user_id,
                        owner_name,
                        description,
                        visibility,
                        _to_iso(created_at),
                        _to_iso(expires_at),
                        max_downloads,
                        BundleStatus.ACTIVE.value,
                    ),
                )

                for position, item in enumerate(items, start=1):
                    self.connection.execute(
                        """
                        INSERT INTO bundle_items (
                            bundle_code,
                            position,
                            type,
                            telegram_file_id,
                            local_path,
                            text,
                            caption,
                            file_name,
                            mime_type,
                            size,
                            metadata_json,
                            created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            code,
                            position,
                            item.type.value,
                            item.telegram_file_id,
                            item.local_path,
                            item.text,
                            item.caption,
                            item.file_name,
                            item.mime_type,
                            item.size,
                            item.metadata_json,
                            _to_iso(created_at),
                        ),
                    )

                self.connection.commit()
            except Exception:
                self.connection.rollback()
                raise

        bundle = self.get_bundle(code)
        if bundle is None:
            raise RuntimeError("Bundle was created but could not be loaded.")
        return bundle

    def get_bundle(self, code: str) -> Bundle | None:
        with self.lock:
            bundle_row = self.connection.execute("SELECT * FROM bundles WHERE code = ?", (code,)).fetchone()
            if bundle_row is None:
                return None

            item_rows = self.connection.execute(
                "SELECT * FROM bundle_items WHERE bundle_code = ? ORDER BY position ASC",
                (code,),
            ).fetchall()

        return _bundle_from_rows(bundle_row, item_rows)

    def increment_download_count(self, code: str) -> None:
        with self.lock:
            self.connection.execute(
                "UPDATE bundles SET download_count = download_count + 1 WHERE code = ?",
                (code,),
            )
            self.connection.commit()

    def mark_deleted(self, code: str) -> bool:
        with self.lock:
            cursor = self.connection.execute(
                "UPDATE bundles SET status = ? WHERE code = ? AND status != ?",
                (BundleStatus.DELETED.value, code, BundleStatus.DELETED.value),
            )
            self.connection.commit()
            return cursor.rowcount > 0

    def get_admin_stats(self) -> AdminStats:
        now = datetime.now(timezone.utc)
        day_ago = now - timedelta(days=1)
        with self.lock:
            row = self.connection.execute(
                """
                SELECT
                    COUNT(*) AS total_bundles,
                    SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) AS active_bundles,
                    SUM(CASE WHEN status = 'deleted' THEN 1 ELSE 0 END) AS deleted_bundles,
                    SUM(CASE WHEN expires_at IS NOT NULL AND expires_at <= ? THEN 1 ELSE 0 END) AS expired_bundles,
                    COALESCE(SUM(download_count), 0) AS total_downloads,
                    SUM(CASE WHEN created_at >= ? THEN 1 ELSE 0 END) AS recent_bundles_24h
                FROM bundles
                """,
                (_to_iso(now), _to_iso(day_ago)),
            ).fetchone()
            item_row = self.connection.execute("SELECT COUNT(*) AS total_items FROM bundle_items").fetchone()

        return AdminStats(
            total_bundles=int(row["total_bundles"] or 0),
            active_bundles=int(row["active_bundles"] or 0),
            deleted_bundles=int(row["deleted_bundles"] or 0),
            expired_bundles=int(row["expired_bundles"] or 0),
            total_items=int(item_row["total_items"] or 0),
            total_downloads=int(row["total_downloads"] or 0),
            recent_bundles_24h=int(row["recent_bundles_24h"] or 0),
        )

    def recent_bundles(self, *, limit: int = 10) -> list[Bundle]:
        with self.lock:
            rows = self.connection.execute(
                "SELECT code FROM bundles ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [bundle for row in rows if (bundle := self.get_bundle(row["code"])) is not None]


def _bundle_from_rows(bundle_row: sqlite3.Row, item_rows: list[sqlite3.Row]) -> Bundle:
    return Bundle(
        code=bundle_row["code"],
        owner_user_id=int(bundle_row["owner_user_id"]),
        owner_name=bundle_row["owner_name"],
        description=bundle_row["description"],
        visibility=bundle_row["visibility"],
        created_at=_from_iso(bundle_row["created_at"]),
        expires_at=_from_iso_optional(bundle_row["expires_at"]),
        max_downloads=bundle_row["max_downloads"],
        download_count=int(bundle_row["download_count"]),
        status=BundleStatus(bundle_row["status"]),
        items=tuple(_item_from_row(row) for row in item_rows),
    )


def _item_from_row(row: sqlite3.Row) -> BundleItem:
    return BundleItem(
        id=int(row["id"]),
        bundle_code=row["bundle_code"],
        position=int(row["position"]),
        type=ContentType(row["type"]),
        telegram_file_id=row["telegram_file_id"],
        local_path=row["local_path"],
        text=row["text"],
        caption=row["caption"],
        file_name=row["file_name"],
        mime_type=row["mime_type"],
        size=row["size"],
        metadata_json=row["metadata_json"],
        created_at=_from_iso(row["created_at"]),
    )


def _to_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat()


def _from_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _from_iso_optional(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None
