from __future__ import annotations

import re


PREFIX_FALLBACK_PATTERN = re.compile(r"^[A-Za-z]+")
TRAILING_PUNCTUATION = " \t\r\n,.;:!?)]}>\"'"


class CodeParser:
    def __init__(self, pattern: str) -> None:
        self.regex = re.compile(pattern)

    def extract_codes(self, text: str) -> list[str]:
        codes: list[str] = []
        seen: set[str] = set()

        for match in self.regex.finditer(text):
            code = self._pick_match_value(match)
            code = code.strip(TRAILING_PUNCTUATION)
            if not code:
                continue
            if code in seen:
                continue
            seen.add(code)
            codes.append(code)

        return codes

    @staticmethod
    def extract_prefix(code: str) -> str | None:
        for delimiter in ("-", "_", ":", "|"):
            if delimiter in code:
                prefix = code.split(delimiter, 1)[0].strip()
                if prefix:
                    return prefix.upper()

        matched = PREFIX_FALLBACK_PATTERN.match(code)
        if matched is None:
            return None
        return matched.group(0).upper()

    @staticmethod
    def _pick_match_value(match: re.Match[str]) -> str:
        if not match.groups():
            return match.group(0)

        for group in match.groups():
            if group:
                return group

        return match.group(0)
