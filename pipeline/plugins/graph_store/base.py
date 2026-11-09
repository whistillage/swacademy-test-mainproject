"""그래프 저장소 인터페이스.

그래프 DB 종류가 정해지면 이 인터페이스를 구현한 플러그인(예: neo4j_store.py)을 추가하고
config.yaml 의 graph_store.name 만 바꾸면 된다.
파이프라인이 그래프에 요구하는 기능은 아래 추상 메서드가 전부다.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Collection, Iterator
from dataclasses import dataclass, field
from typing import Any, ClassVar

from ...registry import Registry


class GraphDataError(ValueError):
    """그래프 데이터 형식이 잘못됐을 때."""


@dataclass
class Node:
    id: str
    label: str  # 노드 종류. aspects.yaml 의 labels 키와 대응
    name: str  # 대표 이름. 프롬프트에 들어가는 표현
    aliases: list[str] = field(default_factory=list)
    description: str = ""
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class Edge:
    source: str
    target: str
    type: str  # 관계 종류. aspects.yaml 의 path 와 대응
    properties: dict[str, Any] = field(default_factory=dict)


class GraphStore(ABC):
    plugin_name: ClassVar[str] = ""

    @abstractmethod
    def iter_nodes(self) -> Iterator[Node]:
        """모든 노드. 대상 노드 검색용 인덱스를 만들 때 쓴다."""

    @abstractmethod
    def get_node(self, node_id: str) -> Node | None:
        """id 로 노드 조회. 없으면 None."""

    @abstractmethod
    def out_edges(self, node_id: str, types: Collection[str] | None = None) -> list[Edge]:
        """node_id 에서 나가는 관계. types 가 None 이면 모든 종류."""

    @abstractmethod
    def stats(self) -> dict[str, Any]:
        """노드/관계 수 등 요약 정보."""

    def close(self) -> None:
        """연결 정리 (서버형 DB 용). 기본은 아무것도 하지 않는다."""


REGISTRY: Registry[GraphStore] = Registry("graph_store", GraphStore, __package__)
register = REGISTRY.register
