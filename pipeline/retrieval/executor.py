"""02 GraphRAG 검색: 속성별 쿼리를 그래프에서 실행한다.

쿼리 하나 = 대상 노드의 속성값 읽기(properties) + path 에 적힌 관계를 hop 별로 따라가며 값 수집
           + sparql 이 있으면 SPARQL 실행 (?target 에 대상 노드를 넣는다).
결과가 없으면 상위 개념(aspects.yaml 의 parent_relation, 기본 IS_A)을 따라 올라가 같은 쿼리를 다시 실행한다.
path / properties 는 그래프 저장소의 get_node / out_edges 만 쓰므로 DB 종류와 무관하게 동작한다.
sparql 은 저장소의 query() 를 쓰므로 SPARQL 을 지원하는 저장소(rdf)에서만 동작한다.
"""

from __future__ import annotations

from ..plugins.graph_store.base import GraphStore
from ..query.planner import AspectCatalog
from ..schemas import AspectQuery, AspectResult, Fact, QueryPlan, RetrievalResult

_MAX_FRONTIER = 200  # hop 마다 따라갈 경로 수 상한 (관계가 아주 많은 노드 대비)


class QueryExecutor:
    def __init__(self, store: GraphStore, catalog: AspectCatalog) -> None:
        self.store = store
        self.catalog = catalog

    def execute(self, plan: QueryPlan) -> RetrievalResult:
        return RetrievalResult(results=[self._run(q) for q in plan.queries])

    def _run(self, query: AspectQuery) -> AspectResult:
        facts = self._collect(query.target_id, query)
        if facts:
            return AspectResult(query.target_id, query.aspect, "found", facts, query.target_id)
        if query.inherit and self.catalog.parent_relation:
            for ancestor in self._ancestors(query.target_id):
                facts = self._collect(ancestor, query)
                if facts:
                    return AspectResult(query.target_id, query.aspect, "inherited", facts, ancestor)
        return AspectResult(query.target_id, query.aspect, "missing")

    def _ancestors(self, node_id: str) -> list[str]:
        """가까운 상위 개념부터 순서대로."""
        assert self.catalog.parent_relation is not None
        found: list[str] = []
        level = [node_id]
        visited = {node_id}
        for _ in range(self.catalog.max_inherit_depth):
            next_level = []
            for current in level:
                for edge in self.store.out_edges(current, [self.catalog.parent_relation]):
                    if edge.target not in visited:
                        visited.add(edge.target)
                        found.append(edge.target)
                        next_level.append(edge.target)
            level = next_level
        return found

    def _collect(self, node_id: str, query: AspectQuery) -> list[Fact]:
        facts: list[Fact] = []
        node = self.store.get_node(node_id)
        if node is not None:
            for key in query.properties:
                value = node.properties.get(key)
                if value is None or value == "":
                    continue
                for v in value if isinstance(value, list) else [value]:
                    facts.append(Fact(names=[str(v)], node_ids=[node_id], relations=[f"@{key}"], kind="property"))
        if query.path:
            facts.extend(self._traverse(node_id, query.path))
        if query.sparql:
            facts.extend(self._sparql(node_id, query.sparql))
        return facts[: self.catalog.max_facts_per_aspect]

    def _sparql(self, node_id: str, sparql: str) -> list[Fact]:
        """행마다 Fact 하나. 대표값은 ?value (없으면 첫 번째 변수). 값이 없는 행은 버린다."""
        facts = []
        for row in self.store.query(sparql, {"target": node_id}):
            value = row.get("value", next(iter(row.values()), None))
            if value is None or value == "":
                continue
            facts.append(Fact(names=[str(value)], node_ids=[node_id], relations=["sparql"],
                              kind="sparql", values=row))
        return facts

    def _traverse(self, start: str, path: list[list[str]]) -> list[Fact]:
        """path 를 따라가며 경로를 모은다. 중간에 더 갈 곳이 없으면 거기까지를 결과로 쓴다."""
        parent = self.catalog.parent_relation
        results: list[tuple[list[str], list[str]]] = []
        frontier: list[tuple[list[str], list[str]]] = [([start], [])]
        for hop in path:
            types = None if "*" in hop else hop
            next_frontier: list[tuple[list[str], list[str]]] = []
            for nodes, rels in frontier:
                edges = [
                    e for e in self.store.out_edges(nodes[-1], types)
                    # "*" 라도 상위 개념 관계는 따라가지 않는다 (상속은 따로 처리)
                    if e.target not in nodes and not (types is None and e.type == parent)
                ]
                if not edges and rels:
                    results.append((nodes, rels))
                for e in edges:
                    next_frontier.append((nodes + [e.target], rels + [e.type]))
            frontier = next_frontier[:_MAX_FRONTIER]
        results.extend(frontier)

        facts = []
        for nodes, rels in results:
            names = [(n.name if (n := self.store.get_node(i)) else i) for i in nodes[1:]]
            facts.append(Fact(names=names, node_ids=nodes[1:], relations=rels))
        return facts
