"""사용자 지정 속성 사전 (config/lexicon.yaml).

요청 문장에서 '빨간', '초록색' 같은 표현을 찾아 (속성, 대표값) 으로 바꾼다.
표현은 단어가 시작하는 위치에서만 찾는다 (앞 글자가 한글/영문/숫자가 아니어야 함).
같은 위치에서는 긴 표현이 우선한다 ('빨간색' 이 '빨간' 보다 먼저).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass
class AttributeMatch:
    aspect: str  # 예: color
    value: str  # 대표값. 예: 빨강
    surface: str  # 문장에 실제로 나온 표현. 예: 빨간
    start: int
    end: int


class Lexicon:
    def __init__(self, data: dict[str, Any]) -> None:
        self.ignore_words: set[str] = {str(w) for w in data.get("ignore_words") or []}
        self._lookup: dict[str, tuple[str, str]] = {}
        for aspect, values in (data.get("attributes") or {}).items():
            for value, surfaces in (values or {}).items():
                for surface in [value, *(surfaces or [])]:
                    self._lookup.setdefault(str(surface).lower(), (str(aspect), str(value)))
        surfaces = sorted(self._lookup, key=len, reverse=True)
        self._regex = (
            re.compile(
                r"(?<![0-9A-Za-z가-힣])(?:" + "|".join(re.escape(s) for s in surfaces) + ")",
                re.IGNORECASE,
            )
            if surfaces
            else None
        )

    def find_attributes(self, text: str) -> tuple[list[AttributeMatch], str]:
        """속성 표현 목록과, 그 표현을 공백으로 가린 문장(글자 위치는 원문과 같음)을 돌려준다."""
        if self._regex is None:
            return [], text
        matches: list[AttributeMatch] = []
        masked = list(text)
        for m in self._regex.finditer(text):
            aspect, value = self._lookup[m.group(0).lower()]
            matches.append(AttributeMatch(aspect, value, m.group(0), m.start(), m.end()))
            masked[m.start() : m.end()] = " " * (m.end() - m.start())
        return matches, "".join(masked)

    def is_ignored(self, word: str) -> bool:
        return word in self.ignore_words
