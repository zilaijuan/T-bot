from __future__ import annotations

import secrets
import sqlite3
import string
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


@dataclass(frozen=True, slots=True)
class MediaRecord:
    code: str
    media_type: str
    file_id: str
    caption: str | None
    uploader_id: int
    file_name: str | None
    mime_type: str | None
    created_at: str


class Database:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.database_path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row

    def init(self) -> None:
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS media_items (
                code TEXT PRIMARY KEY,
                media_type TEXT NOT NULL,
                file_id TEXT NOT NULL,
                caption TEXT,
                uploader_id INTEGER NOT NULL,
                file_name TEXT,
                mime_type TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        self.connection.commit()

    def create_record(
        self,
        *,
        media_type: str,
        file_id: str,
        caption: str | None,
        uploader_id: int,
        file_name: str | None,
        mime_type: str | None,
        code_length: int,
    ) -> MediaRecord:
        for _ in range(10):
            code = self._generate_code(code_length)
            record = MediaRecord(
                code=code,
                media_type=media_type,
                file_id=file_id,
                caption=caption,
                uploader_id=uploader_id,
                file_name=file_name,
                mime_type=mime_type,
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            try:
                self._insert(record)
                return record
            except sqlite3.IntegrityError:
                continue

        raise RuntimeError("Could not generate a unique pickup code.")

    def get_record(self, code: str) -> MediaRecord | None:
        row = self.connection.execute(
            """
            SELECT code, media_type, file_id, caption, uploader_id, file_name, mime_type, created_at
            FROM media_items
            WHERE code = ?
            """,
            (code,),
        ).fetchone()

        if row is None:
            return None

        return MediaRecord(
            code=row["code"],
            media_type=row["media_type"],
            file_id=row["file_id"],
            caption=row["caption"],
            uploader_id=row["uploader_id"],
            file_name=row["file_name"],
            mime_type=row["mime_type"],
            created_at=row["created_at"],
        )

    def close(self) -> None:
        self.connection.close()

    def _insert(self, record: MediaRecord) -> None:
        self.connection.execute(
            """
            INSERT INTO media_items (
                code,
                media_type,
                file_id,
                caption,
                uploader_id,
                file_name,
                mime_type,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.code,
                record.media_type,
                record.file_id,
                record.caption,
                record.uploader_id,
                record.file_name,
                record.mime_type,
                record.created_at,
            ),
        )
        self.connection.commit()

    @staticmethod
    def _generate_code(code_length: int) -> str:
        return "".join(secrets.choice(CODE_ALPHABET) for _ in range(code_length))
