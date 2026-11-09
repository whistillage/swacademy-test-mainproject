"""단계 사이에 주고받는 데이터 형식.

01 쿼리 구성  -> QueryPlan
02 검색       -> RetrievalResult
03 프롬프트   -> PromptResult
04 이미지     -> GenerationResult (plugins/image_generator/base.py)

모든 결과는 to_dict() 로 output/<실행시각>/ 에 JSON 저장된다.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


class Serializable:
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)  # type: ignore[call-overload]


# ---------------------------------------------------------------- 01 쿼리 구성


@dataclass
class Mention(Serializable):
    """요청 문장에서 찾은 '그릴 대상' 후보 표현. start/end 는 원문 기준 글자 위치."""

    text: str
    start: int
    end: int
    # 이 대상에 사용자가 직접 지정한 속성. 예: {"color": ["빨강"]}
    attributes: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class ParsedRequest(Serializable):
    text: str
    mentions: list[Mention]
    # 어느 대상에도 붙이지 못한 사용자 지정 속성
    unassigned_attributes: dict[str, list[str]] = field(default_factory=dict)
    tokens: list[str] = field(default_factory=list)  # 디버깅용 분석 결과


@dataclass
class LinkedTarget(Serializable):
    """Mention 을 그래프 노드에 연결한 결과. node_id 가 None 이면 그래프에서 못 찾은 것."""

    mention: Mention
    node_id: str | None = None
    node_name: str | None = None
    label: str | None = None
    score: float = 0.0
    method: str = "none"  # exact | hybrid | none
    candidates: list[dict[str, Any]] = field(default_factory=list)  # 검색 후보 (디버깅용)

    @property
    def linked(self) -> bool:
        return self.node_id is not None


@dataclass
class AspectQuery(Serializable):
    """대상 노드 하나의 속성 하나를 찾는 쿼리."""

    target_id: str
    aspect: str
    path: list[list[str]]  # hop 별로 따라갈 관계 종류. "*" 는 모든 관계
    properties: list[str] = field(default_factory=list)  # 노드 속성에서 바로 읽을 key
    inherit: bool = True  # 결과가 없으면 상위 개념에서 가져올지
    sparql: str | None = None  # 있으면 path 대신 이 SPARQL 로 찾는다 (?target = 대상 노드)


@dataclass
class QueryPlan(Serializable):
    request: str
    parsed: ParsedRequest
    targets: list[LinkedTarget]
    queries: list[AspectQuery]
    skipped: list[dict[str, Any]] = field(default_factory=list)  # 쿼리를 만들지 않은 항목과 이유


# ---------------------------------------------------------------- 02 검색


@dataclass
class Fact(Serializable):
    """검색으로 얻은 값 하나.

    names 는 대상 노드 다음부터의 경로. 예: 개구리 -HAS_PART-> 뒷다리 -HAS_FEATURE-> 길다
    => names=["뒷다리", "길다"], relations=["HAS_PART", "HAS_FEATURE"]
    """

    names: list[str]
    node_ids: list[str] = field(default_factory=list)
    relations: list[str] = field(default_factory=list)
    kind: str = "relation"  # relation | property | sparql
    # sparql 결과 행 전체 {변수: 값}. 대표값은 ?value. 날짜, 출처 같은 부가 정보도 여기 남는다.
    values: dict[str, Any] = field(default_factory=dict)


@dataclass
class AspectResult(Serializable):
    target_id: str
    aspect: str
    status: str  # found | inherited | missing
    facts: list[Fact] = field(default_factory=list)
    source_id: str | None = None  # 값을 실제로 가져온 노드 (inherited 면 상위 개념)


@dataclass
class RetrievalResult(Serializable):
    results: list[AspectResult]


# ---------------------------------------------------------------- 03 프롬프트


@dataclass
class PromptResult(Serializable):
    positive: str
    negative: str
    # translator 후처리 전 원문
    source_positive: str
    source_negative: str
    # 대상별로 어떤 값이 어디서 왔는지 (디버깅용)
    slots: list[dict[str, Any]] = field(default_factory=list)
    # 이미지 위에 글자로 찍을 카드 내용 (templates.yaml 의 card). 없으면 빈 dict
    card: dict[str, Any] = field(default_factory=dict)
