"""JSON 파일 기반 그래프 저장소.

실제 그래프 DB 가 정해지기 전까지 쓰는 임시 저장소. 파일 형식:
{
  "schema_version": 1,
  "nodes": [{"id", "label", "name", "aliases"?, "description"?, "properties"?}],
  "edges": [{"source", "target", "type", "properties"?}]
}
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Collection, Iterator
from pathlib import Path
from typing import Any

from ...paths import resolve
from .base import Edge, GraphDataError, GraphStore, Node, register

SCHEMA_VERSION = 1


@register("json")
class JsonGraphStore(GraphStore):
    def __init__(self, path: str) -> None:
        self.path = resolve(path)
        if not self.path.exists():
            raise FileNotFoundError(
                f"그래프 파일이 없습니다: {self.path}\n"
                "먼저 `python graph_db.py init` 으로 빈 그래프 DB 를 만드세요."
            )
        with self.path.open(encoding="utf-8") as f:
            data = json.load(f)
        self._nodes: dict[str, Node] = {}
        self._out: dict[str, list[Edge]] = defaultdict(list)
        self._edge_count = 0
        self._load(data)

    @staticmethod
    def create_empty(path: str | Path, overwrite: bool = False) -> Path:
        target = resolve(path)
        if target.exists() and not overwrite:
            raise FileExistsError(f"이미 존재합니다: {target} (덮어쓰려면 --force)")
        target.parent.mkdir(parents=True, exist_ok=True)
        empty = {"schema_version": SCHEMA_VERSION, "nodes": [], "edges": []}
        target.write_text(json.dumps(empty, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return target

    def iter_nodes(self) -> Iterator[Node]:
        return iter(self._nodes.values())

    def get_node(self, node_id: str) -> Node | None:
        return self._nodes.get(node_id)

    def out_edges(self, node_id: str, types: Collection[str] | None = None) -> list[Edge]:
        edges = self._out.get(node_id, [])
        if types is None:
            return list(edges)
        allowed = set(types)
        return [e for e in edges if e.type in allowed]

    def stats(self) -> dict[str, Any]:
        relation_types = Counter(e.type for edges in self._out.values() for e in edges)
        return {
            "store": "json",
            "path": str(self.path),
            "nodes": len(self._nodes),
            "edges": self._edge_count,
            "labels": dict(Counter(n.label for n in self._nodes.values())),
            "relation_types": dict(relation_types),
        }

    def _load(self, data: dict[str, Any]) -> None:
        errors: list[str] = []
        for i, raw in enumerate(data.get("nodes", [])):
            missing = [k for k in ("id", "label", "name") if not raw.get(k)]
            if missing:
                errors.append(f"nodes[{i}]: {', '.join(missing)} 누락")
                continue
            node_id = str(raw["id"])
            if node_id in self._nodes:
                errors.append(f"nodes[{i}]: id 중복 '{node_id}'")
                continue
            self._nodes[node_id] = Node(
                id=node_id,
                label=str(raw["label"]),
                name=str(raw["name"]),
                aliases=[str(a) for a in raw.get("aliases", [])],
                description=str(raw.get("description", "")),
                properties=dict(raw.get("properties", {})),
            )
        for i, raw in enumerate(data.get("edges", [])):
            missing = [k for k in ("source", "target", "type") if not raw.get(k)]
            if missing:
                errors.append(f"edges[{i}]: {', '.join(missing)} 누락")
                continue
            unknown = [str(raw[k]) for k in ("source", "target") if str(raw[k]) not in self._nodes]
            if unknown:
                errors.append(f"edges[{i}]: 없는 노드 참조 {unknown}")
                continue
            edge = Edge(
                source=str(raw["source"]),
                target=str(raw["target"]),
                type=str(raw["type"]),
                properties=dict(raw.get("properties", {})),
            )
            self._out[edge.source].append(edge)
            self._edge_count += 1
        if errors:
            shown = "\n  ".join(errors[:20])
            more = f"\n  ... 외 {len(errors) - 20}건" if len(errors) > 20 else ""
            raise GraphDataError(f"{self.path} 형식 오류 {len(errors)}건:\n  {shown}{more}")
