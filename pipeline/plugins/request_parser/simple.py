"""형태소 분석기 없이 동작하는 단순 분석기 (대체/비교용, 정확도 낮음).

어절 끝의 조사를 떼어 내고, 동사처럼 끝나는 어절은 버린다.
'고양이' 의 '이' 처럼 명사 끝 글자와 조사가 겹치는 경우를 피하려고 일부 조사는 목록에서 뺐다.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from ...query.lexicon import Lexicon
from .base import RequestParser, register

_WORD = re.compile(r"[0-9A-Za-z가-힣]+")
DEFAULT_JOSA = ("에게서", "으로", "에서", "에게", "한테", "처럼", "까지", "부터", "이랑", "하고",
                "랑", "와", "과", "을", "를", "가", "은", "는", "의", "에", "로")
DEFAULT_VERB_ENDINGS = ("줘", "줘요", "주세요", "줄래", "해줘", "하는", "있는", "그려", "그린")


@register("simple")
class SimpleRequestParser(RequestParser):
    def __init__(
        self,
        lexicon: Lexicon,
        josa: Iterable[str] = DEFAULT_JOSA,
        verb_endings: Iterable[str] = DEFAULT_VERB_ENDINGS,
    ) -> None:
        super().__init__(lexicon)
        self.josa = sorted(josa, key=len, reverse=True)
        self.verb_endings = tuple(verb_endings)

    def extract_mentions(self, text: str) -> tuple[list[tuple[int, int]], list[str]]:
        spans: list[tuple[int, int]] = []
        tokens: list[str] = []
        for m in _WORD.finditer(text):
            word = m.group(0)
            tokens.append(word)
            if word.endswith(self.verb_endings):
                continue
            end = m.end()
            for josa in self.josa:
                if word.endswith(josa) and len(word) > len(josa):
                    end -= len(josa)
                    break
            spans.append((m.start(), end))
        return spans, tokens
