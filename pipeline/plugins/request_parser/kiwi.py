"""Kiwi 형태소 분석기로 대상 후보 명사를 뽑는다 (기본값).

붙어 있는 명사는 하나로 합친다. 예: 청/NNG + 개구리/NNG -> 청개구리
"""

from __future__ import annotations

from collections.abc import Iterable
from functools import lru_cache
from typing import Any

from ...query.lexicon import Lexicon
from .base import RequestParser, register


@lru_cache(maxsize=1)
def _shared_kiwi() -> Any:
    """Kiwi 모델 로드는 수 초 걸리므로 프로세스당 한 번만 한다."""
    from kiwipiepy import Kiwi

    return Kiwi()


@register("kiwi")
class KiwiRequestParser(RequestParser):
    def __init__(self, lexicon: Lexicon, noun_tags: Iterable[str] = ("NNG", "NNP", "SL")) -> None:
        super().__init__(lexicon)
        self._kiwi = _shared_kiwi()
        self.noun_tags = set(noun_tags)

    def extract_mentions(self, text: str) -> tuple[list[tuple[int, int]], list[str]]:
        tokens = self._kiwi.tokenize(text)
        spans: list[tuple[int, int]] = []
        current: tuple[int, int] | None = None
        for tok in tokens:
            start, end = tok.start, tok.start + tok.len
            if tok.tag in self.noun_tags:
                if current is not None and current[1] == start:
                    current = (current[0], end)
                else:
                    if current is not None:
                        spans.append(current)
                    current = (start, end)
            elif current is not None:
                spans.append(current)
                current = None
        if current is not None:
            spans.append(current)
        return spans, [f"{t.form}/{t.tag}" for t in tokens]
