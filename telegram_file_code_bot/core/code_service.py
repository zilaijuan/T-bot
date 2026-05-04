from __future__ import annotations

import re
import secrets
from collections import Counter
from collections.abc import Callable, Iterable

from telegram_file_code_bot.core.models import BundleItemInput, ContentType


CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_FIND_PATTERN = re.compile(r"\b[A-Z]\d+(?:[A-Z]\d+)*-[A-Z2-9]+\b", re.IGNORECASE)


class CodeService:
    def __init__(self, *, random_length: int, max_summary_length: int | None) -> None:
        self.random_length = random_length
        self.max_summary_length = max_summary_length

    def build_summary(self, items: Iterable[BundleItemInput]) -> str:
        counts = Counter(item.type for item in items)
        audio_count = counts[ContentType.AUDIO] + counts[ContentType.VOICE]
        parts: list[str] = []

        if counts[ContentType.TEXT]:
            parts.append(f"T{counts[ContentType.TEXT]}")
        if counts[ContentType.PHOTO]:
            parts.append(f"P{counts[ContentType.PHOTO]}")
        if counts[ContentType.VIDEO]:
            parts.append(f"V{counts[ContentType.VIDEO]}")
        if counts[ContentType.DOCUMENT]:
            parts.append(f"F{counts[ContentType.DOCUMENT]}")
        if audio_count:
            parts.append(f"A{audio_count}")

        summary = "".join(parts)
        if self.max_summary_length is not None and len(summary) > self.max_summary_length:
            raise ValueError("取件码摘要过长，无法生成取件码。请减少内容数量，或联系管理员调整配置。")
        return summary

    def generate_code(self, items: Iterable[BundleItemInput], exists: Callable[[str], bool]) -> str:
        summary = self.build_summary(items)
        if not summary:
            raise ValueError("内容包必须至少包含一条内容。")

        for _ in range(50):
            random_part = "".join(secrets.choice(CODE_ALPHABET) for _ in range(self.random_length))
            code = f"{summary}-{random_part}"
            if not exists(code):
                return code
        raise RuntimeError("无法生成唯一取件码，请稍后重试。")


def normalize_code(raw_code: str) -> str:
    return raw_code.strip().upper().replace(" ", "").replace("_", "-")


def extract_codes(raw_text: str) -> list[str]:
    codes: list[str] = []
    seen: set[str] = set()
    for match in CODE_FIND_PATTERN.finditer(raw_text):
        code = normalize_code(match.group(0))
        if code not in seen:
            seen.add(code)
            codes.append(code)
    return codes
