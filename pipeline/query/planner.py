"""속성별 쿼리 생성 (01 쿼리 구성의 3단계).

대상 노드의 종류(label)에 맞는 속성 체크리스트(config/aspects.yaml)를 보고
속성마다 쿼리를 하나씩 만든다. 사용자가 요청에서 직접 지정한 속성은 그래프에서 찾지 않는다.

속성을 찾는 방법은 셋 중 하나 이상
  path       관계를 hop 별로 따라가기 (모든 그래프 저장소)
  properties 노드 자체 속성 읽기 (모든 그래프 저장소)
  sparql     SPARQL 질의 (SPARQL 을 지원하는 저장소, 예: rdf)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..schemas import AspectQuery, LinkedTarget


@dataclass
class AspectSpec:
    name: str
    path: list[list[str]]
    properties: list[str]
    inherit: bool
    sparql: str | None = None


class AspectCatalog:
    """aspects.yaml 해석. 검색(02)과 프롬프트(03) 단계도 같은 정의를 쓴다."""

    DEFAULT_LABEL = "_default"

    def __init__(self, data: dict[str, Any]) -> None:
        settings = data.get("settings") or {}
        self.parent_relation: str | None = settings.get("parent_relation", "IS_A")
        self.max_inherit_depth = int(settings.get("max_inherit_depth", 3))
        self.max_facts_per_aspect = int(settings.get("max_facts_per_aspect", 5))
        self._labels: dict[str, list[AspectSpec]] = {
            str(label): [self._parse(str(label), str(name), spec) for name, spec in (aspects or {}).items()]
            for label, aspects in (data.get("labels") or {}).items()
        }

    def aspects_for(self, label: str | None) -> list[AspectSpec]:
        if label is not None and label in self._labels:
            return self._labels[label]
        return self._labels.get(self.DEFAULT_LABEL, [])

    @staticmethod
    def _parse(label: str, name: str, spec: dict[str, Any] | None) -> AspectSpec:
        spec = spec or {}
        path = [[str(h) for h in ([hop] if isinstance(hop, str) else hop)] for hop in spec.get("path", [])]
        properties = [str(p) for p in spec.get("properties", [])]
        sparql = spec.get("sparql") or None
        if not path and not properties and not sparql:
            raise ValueError(
                f"aspects.yaml labels.{label}.{name}: path, properties, sparql 중 하나는 필요합니다."
            )
        return AspectSpec(
            name=name,
            path=path,
            properties=properties,
            inherit=bool(spec.get("inherit", True)),
            sparql=str(sparql) if sparql else None,
        )


class QueryPlanner:
    def __init__(self, catalog: AspectCatalog) -> None:
        self.catalog = catalog

    def plan(self, targets: list[LinkedTarget]) -> tuple[list[AspectQuery], list[dict[str, Any]]]:
        queries: list[AspectQuery] = []
        skipped: list[dict[str, Any]] = []
        for target in targets:
            if not target.linked:
                skipped.append({"mention": target.mention.text, "reason": "그래프에서 대상 노드를 찾지 못함"})
                continue
            assert target.node_id is not None
            for spec in self.catalog.aspects_for(target.label):
                if spec.name in target.mention.attributes:
                    skipped.append({
                        "target_id": target.node_id,
                        "aspect": spec.name,
                        "reason": "사용자 지정 값 사용",
                        "value": target.mention.attributes[spec.name],
                    })
                    continue
                queries.append(AspectQuery(
                    target_id=target.node_id,
                    aspect=spec.name,
                    path=spec.path,
                    properties=spec.properties,
                    inherit=spec.inherit,
                    sparql=spec.sparql,
                ))
        return queries, skipped
