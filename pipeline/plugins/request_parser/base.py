"""요청 분석기 인터페이스: 요청 문장 -> 그릴 대상 후보(Mention) + 사용자 지정 속성.

처리 순서 (parse)
  1. 사전(lexicon.yaml)으로 사용자 지정 속성 표현을 찾고 문장에서 가린다   <- 공통
  2. 남은 문장에서 대상 후보 명사 위치를 뽑는다                            <- 플러그인 (extract_mentions)
  3. 띄어 쓴 영문 단어가 이어지면 하나로 합친다 ('Engro Holdings Limited')  <- 공통
  4. 각 속성을 가장 가까운 대상에 붙인다 (뒤쪽 대상 우선, 없으면 앞쪽)     <- 공통

플러그인은 보통 extract_mentions() 만 구현하면 된다.
나중에 LLM 기반 분석기처럼 전부 직접 처리하고 싶으면 parse() 를 재정의한다.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import ClassVar

from ...query.lexicon import AttributeMatch, Lexicon
from ...registry import Registry
from ...schemas import Mention, ParsedRequest


class RequestParser(ABC):
    plugin_name: ClassVar[str] = ""

    def __init__(self, lexicon: Lexicon) -> None:
        self.lexicon = lexicon

    @abstractmethod
    def extract_mentions(self, text: str) -> tuple[list[tuple[int, int]], list[str]]:
        """대상 후보 명사의 (start, end) 위치 목록과 디버깅용 토큰 목록.

        text 는 사용자 지정 속성 표현이 공백으로 가려진 문장이다 (글자 위치는 원문과 같음).
        """

    def parse(self, text: str) -> ParsedRequest:
        attribute_matches, masked = self.lexicon.find_attributes(text)
        spans, tokens = self.extract_mentions(masked)
        spans = _merge_latin_runs(text, spans)

        mentions: list[Mention] = []
        seen: set[str] = set()
        for start, end in spans:
            word = text[start:end].strip()
            if not word or self.lexicon.is_ignored(word) or word in seen:
                continue
            seen.add(word)
            mentions.append(Mention(text=word, start=start, end=end))

        unassigned = _assign_attributes(mentions, attribute_matches)
        return ParsedRequest(
            text=text, mentions=mentions, unassigned_attributes=unassigned, tokens=tokens
        )


_LATIN = re.compile(r"[0-9A-Za-z][0-9A-Za-z.&'-]*")


def _merge_latin_runs(text: str, spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """공백으로만 떨어진 영문 단어 후보를 하나로 합친다. 예: Engro / Holdings / Limited -> Engro Holdings Limited

    형태소 분석기는 띄어 쓴 영문 이름을 단어마다 따로 뽑는다. 그러면 'Limited' 처럼 흔한 단어가
    다른 회사 이름에 잘못 연결된다. 사이 간격은 원문으로 확인하므로, 속성 표현(가려진 부분)을
    사이에 둔 단어는 합치지 않는다.
    """
    merged: list[tuple[int, int]] = []
    for start, end in spans:
        if merged:
            prev_start, prev_end = merged[-1]
            gap = text[prev_end:start]
            if (
                gap and gap.isspace()
                and _LATIN.fullmatch(text[prev_start:prev_end].split()[-1])
                and _LATIN.fullmatch(text[start:end])
            ):
                merged[-1] = (prev_start, end)
                continue
        merged.append((start, end))
    return merged


def _assign_attributes(
    mentions: list[Mention], matches: list[AttributeMatch]
) -> dict[str, list[str]]:
    """속성 표현을 바로 뒤의 대상에 붙인다 ('빨간 개구리'). 뒤에 없으면 바로 앞 대상에 붙인다."""
    unassigned: dict[str, list[str]] = {}
    for match in matches:
        after = [m for m in mentions if m.start >= match.end]
        before = [m for m in mentions if m.end <= match.start]
        owner = after[0] if after else (before[-1] if before else None)
        bucket = owner.attributes if owner else unassigned
        values = bucket.setdefault(match.aspect, [])
        if match.value not in values:
            values.append(match.value)
    return unassigned


REGISTRY: Registry[RequestParser] = Registry("request_parser", RequestParser, __package__)
register = REGISTRY.register
