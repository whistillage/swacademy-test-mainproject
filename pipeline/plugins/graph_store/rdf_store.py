"""RDF 파일(.ttl 등) 기반 그래프 저장소. rdflib 로 읽고 SPARQL 질의를 지원한다.

노드와 관계로 바꾸는 규칙 (대상 노드 찾기와 경로 탐색용)
  - 노드 id   : CURIE (예: psx:company_3). 접두어가 없으면 전체 IRI
  - label      : rdf:type 의 로컬 이름 (예: Company)
  - name       : name_predicates 중 처음 찾은 값
  - aliases    : alias_predicates 의 모든 값 (name 제외)
  - properties : 리터럴 값을 갖는 술어. key 는 술어의 로컬 이름 (예: hasCompanyIdentifier)
  - 관계       : IRI 를 가리키는 술어 (rdf:type 제외). type 은 술어의 로컬 이름

대상 노드 찾기 인덱스에는 index_classes 에 적은 종류의 노드만 넣는다.
(관측치처럼 수천 개인 노드까지 임베딩하지 않도록)

SPARQL 에서는 파일에 선언된 접두어(@prefix)를 그대로 쓸 수 있다.
"""

from __future__ import annotations

from collections import Counter
from decimal import Decimal
from collections.abc import Collection, Iterator
from typing import Any

from ...paths import resolve
from .base import Edge, GraphDataError, GraphStore, Node, register

_DEFAULT_NAME_PREDICATES = ("rdfs:label", "skos:prefLabel")
_DEFAULT_ALIAS_PREDICATES = ("rdfs:label", "skos:prefLabel", "skos:altLabel")
_WELL_KNOWN = {
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    "skos": "http://www.w3.org/2004/02/skos/core#",
    "xsd": "http://www.w3.org/2001/XMLSchema#",
    "owl": "http://www.w3.org/2002/07/owl#",
}


@register("rdf")
class RdfGraphStore(GraphStore):
    def __init__(
        self,
        paths: list[str] | str,
        index_classes: list[str] | None = None,
        name_predicates: list[str] | None = None,
        alias_predicates: list[str] | None = None,
        prefixes: dict[str, str] | None = None,
    ) -> None:
        from rdflib import Graph

        self.paths = [resolve(p) for p in ([paths] if isinstance(paths, str) else paths)]
        self.graph = Graph()
        for name, uri in _WELL_KNOWN.items():
            self.graph.bind(name, uri, override=False)
        for path in self.paths:
            if not path.exists():
                raise FileNotFoundError(f"그래프 파일이 없습니다: {path}")
            try:
                self.graph.parse(path)
            except Exception as exc:  # rdflib 은 형식마다 다른 예외를 낸다
                raise GraphDataError(f"{path} 를 읽지 못했습니다: {exc}") from exc
        for name, uri in (prefixes or {}).items():
            self.graph.bind(name, uri, override=True)
        self._ns = {prefix: str(uri) for prefix, uri in self.graph.namespaces()}

        self.index_classes = [self._term(c) for c in index_classes or []]
        self.name_predicates = [self._term(p) for p in name_predicates or _DEFAULT_NAME_PREDICATES]
        self.alias_predicates = [self._term(p) for p in alias_predicates or _DEFAULT_ALIAS_PREDICATES]
        self._nodes: dict[str, Node] = {}

    # ---------------------------------------------------------------- GraphStore

    def iter_nodes(self) -> Iterator[Node]:
        from rdflib import RDF

        seen: set[Any] = set()
        classes = self.index_classes or sorted(set(self.graph.objects(None, RDF.type)))
        for cls in classes:
            for subject in self.graph.subjects(RDF.type, cls):
                if subject not in seen:
                    seen.add(subject)
                    node = self.get_node(self._id(subject))
                    if node is not None:
                        yield node

    def get_node(self, node_id: str) -> Node | None:
        if node_id in self._nodes:
            return self._nodes[node_id]
        node = self._build_node(self._term(node_id))
        if node is not None:
            self._nodes[node_id] = node
        return node

    def out_edges(self, node_id: str, types: Collection[str] | None = None) -> list[Edge]:
        from rdflib import RDF, Literal

        allowed = set(types) if types is not None else None
        edges = []
        for predicate, obj in self.graph.predicate_objects(self._term(node_id)):
            if predicate == RDF.type or isinstance(obj, Literal):
                continue
            kind = _local(predicate)
            if allowed is None or kind in allowed:
                edges.append(Edge(source=node_id, target=self._id(obj), type=kind))
        return edges

    def stats(self) -> dict[str, Any]:
        from rdflib import RDF, Literal

        labels = Counter(_local(o) for o in self.graph.objects(None, RDF.type))
        relations = Counter(
            _local(p) for _, p, o in self.graph if p != RDF.type and not isinstance(o, Literal)
        )
        return {
            "store": "rdf",
            "paths": [str(p) for p in self.paths],
            "triples": len(self.graph),
            "indexed_nodes": sum(1 for _ in self.iter_nodes()),
            "labels": dict(labels.most_common()),
            "relation_types": dict(relations.most_common()),
        }

    def query(self, sparql: str, bindings: dict[str, str]) -> list[dict[str, Any]]:
        from rdflib import Literal

        init = {name: self._term(value) for name, value in bindings.items()}
        try:
            result = self.graph.query(sparql, initBindings=init)
        except Exception as exc:
            raise GraphDataError(f"SPARQL 실행 실패: {exc}\n--- 쿼리 ---\n{sparql.strip()}") from exc
        rows = []
        for row in result:
            values: dict[str, Any] = {}
            for name, term in row.asdict().items():
                values[str(name)] = _python(term) if isinstance(term, Literal) else self._id(term)
            rows.append(values)
        return rows

    # ---------------------------------------------------------------- 변환

    def _build_node(self, subject: Any) -> Node | None:
        from rdflib import RDF, Literal

        if (subject, None, None) not in self.graph:
            return None
        types = [_local(t) for t in self.graph.objects(subject, RDF.type)]
        names = [str(v) for p in self.name_predicates for v in self.graph.objects(subject, p)]
        aliases = [str(v) for p in self.alias_predicates for v in self.graph.objects(subject, p)]
        properties: dict[str, Any] = {}
        for predicate, obj in self.graph.predicate_objects(subject):
            if isinstance(obj, Literal):
                properties.setdefault(_local(predicate), []).append(_python(obj))
        node_id = self._id(subject)
        name = names[0] if names else _local(subject)
        return Node(
            id=node_id,
            label=self._label(types),
            name=name,
            aliases=list(dict.fromkeys(a for a in aliases if a != name)),
            properties={k: v[0] if len(v) == 1 else v for k, v in properties.items()},
        )

    def _label(self, types: list[str]) -> str:
        """index_classes 에 있는 종류를 우선한다. 예: [Company, ObservedEntity] -> Company"""
        preferred = {_local(c) for c in self.index_classes}
        for t in types:
            if t in preferred:
                return t
        return types[0] if types else "Resource"

    def _id(self, term: Any) -> str:
        uri = str(term)
        best = ""
        for prefix, ns in self._ns.items():
            if uri.startswith(ns) and len(ns) > len(best):
                best, chosen = ns, prefix
        if best and uri[len(best):] and all(c.isalnum() or c in "_-." for c in uri[len(best):]):
            return f"{chosen}:{uri[len(best):]}"
        return uri

    def _term(self, node_id: str) -> Any:
        from rdflib import URIRef

        return URIRef(self._iri(node_id))

    def _iri(self, curie: str) -> str:
        """'psx:company_3' -> 전체 IRI. 이미 IRI 면 그대로."""
        prefix, sep, local = curie.partition(":")
        if sep and not local.startswith("//") and prefix in self._ns:
            return self._ns[prefix] + local
        return curie


def _python(literal: Any) -> Any:
    """리터럴 -> 파이썬 값. xsd:decimal(Decimal)은 JSON 에 숫자로 남도록 float 로 바꾼다."""
    value = literal.toPython()
    return float(value) if isinstance(value, Decimal) else value


def _local(term: Any) -> str:
    uri = str(term)
    for sep in ("#", "/"):
        if sep in uri:
            uri = uri.rsplit(sep, 1)[1] or uri
    return uri
