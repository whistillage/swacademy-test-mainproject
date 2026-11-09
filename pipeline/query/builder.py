"""01 쿼리 구성: 요청 분석 -> 대상 노드 찾기 -> 속성별 쿼리 생성."""

from __future__ import annotations

from ..plugins.request_parser.base import RequestParser
from ..schemas import LinkedTarget, QueryPlan
from .linker import HybridLinker
from .planner import QueryPlanner


class QueryBuilder:
    def __init__(self, parser: RequestParser, linker: HybridLinker, planner: QueryPlanner) -> None:
        self.parser = parser
        self.linker = linker
        self.planner = planner

    def build(self, request: str) -> QueryPlan:
        parsed = self.parser.parse(request)
        targets = _merge_same_node(self.linker.link(parsed.mentions))
        queries, skipped = self.planner.plan(targets)
        return QueryPlan(request=request, parsed=parsed, targets=targets, queries=queries, skipped=skipped)


def _merge_same_node(targets: list[LinkedTarget]) -> list[LinkedTarget]:
    """서로 다른 표현이 같은 노드를 가리키면 (예: '개구리', 'frog') 하나로 합친다."""
    merged: list[LinkedTarget] = []
    by_node: dict[str, LinkedTarget] = {}
    for target in targets:
        if target.node_id is None:
            merged.append(target)
            continue
        first = by_node.get(target.node_id)
        if first is None:
            by_node[target.node_id] = target
            merged.append(target)
            continue
        for aspect, values in target.mention.attributes.items():
            bucket = first.mention.attributes.setdefault(aspect, [])
            bucket.extend(v for v in values if v not in bucket)
    return merged
