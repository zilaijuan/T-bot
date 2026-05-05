from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from telegram import Bot
from telegram.error import TelegramError

from backup_bot.config import BackupSettings


LOGGER = logging.getLogger(__name__)
HASH_CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True, slots=True)
class BackupRunResult:
    checked: int
    sent: int
    skipped: int
    missing: int
    delete_failed: int

    def to_text(self) -> str:
        return (
            "备份检查完成。\n"
            f"检查文件：{self.checked}\n"
            f"已发送：{self.sent}\n"
            f"未变化跳过：{self.skipped}\n"
            f"文件不存在：{self.missing}\n"
            f"旧消息删除失败：{self.delete_failed}"
        )


class BackupService:
    def __init__(self, settings: BackupSettings) -> None:
        self.settings = settings

    async def run_once(self, bot: Bot) -> BackupRunResult:
        state = self._load_state()
        sent = 0
        skipped = 0
        missing = 0
        delete_failed = 0

        for path in self.settings.backup_paths:
            normalized_path = str(path)
            if not path.exists() or not path.is_file():
                missing += 1
                LOGGER.warning("Backup file does not exist: %s", path)
                continue

            file_hash = _sha256_file(path)
            file_state = state.get(normalized_path, {})
            if file_state.get("sha256") == file_hash:
                skipped += 1
                continue

            old_message_id = file_state.get("message_id")
            if self.settings.delete_old and old_message_id:
                try:
                    await bot.delete_message(chat_id=self.settings.chat_id, message_id=int(old_message_id))
                except TelegramError as exc:
                    delete_failed += 1
                    LOGGER.warning("Could not delete old backup message for %s: %s", path, exc)

            caption = self._build_caption(path, file_hash)
            with path.open("rb") as file_handle:
                message = await bot.send_document(
                    chat_id=self.settings.chat_id,
                    document=file_handle,
                    filename=path.name,
                    caption=caption,
                )

            state[normalized_path] = {
                "sha256": file_hash,
                "message_id": message.message_id,
                "sent_at": datetime.now(timezone.utc).isoformat(),
                "size": path.stat().st_size,
            }
            sent += 1

        self._save_state(state)
        return BackupRunResult(
            checked=len(self.settings.backup_paths),
            sent=sent,
            skipped=skipped,
            missing=missing,
            delete_failed=delete_failed,
        )

    def status_text(self) -> str:
        state = self._load_state()
        lines = [
            "SQLite 备份状态",
            f"目标群组：{self.settings.chat_id}",
            f"检查间隔：{self.settings.interval_seconds} 秒",
            f"删除旧文件：{'开启' if self.settings.delete_old else '关闭'}",
            "文件：",
        ]
        for path in self.settings.backup_paths:
            file_state = state.get(str(path), {})
            sha = file_state.get("sha256", "未备份")
            sent_at = file_state.get("sent_at", "未备份")
            lines.append(f"- {path} | {sha[:12]} | {sent_at}")
        return "\n".join(lines)

    def _build_caption(self, path: Path, file_hash: str) -> str:
        return (
            f"{self.settings.caption_prefix}\n"
            f"file: {path.name}\n"
            f"sha256: {file_hash[:16]}\n"
            f"time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
        )

    def _load_state(self) -> dict[str, dict[str, Any]]:
        path = self.settings.state_path
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            LOGGER.exception("Could not read backup state file: %s", path)
            return {}
        return data if isinstance(data, dict) else {}

    def _save_state(self, state: dict[str, dict[str, Any]]) -> None:
        path = self.settings.state_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(HASH_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()
