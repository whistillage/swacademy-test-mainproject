"""대상 노드 찾기 (01 쿼리 구성의 2단계): Mention -> 그래프 노드.

하이브리드 검색
  1) 정확히 일치 (이름/별칭)               -> 바로 확정
  2) 키워드 검색 (문자 2-gram BM25)        ┐
  3) 벡터 검색  (임베딩 코사인 유사도)     ┴-> RRF 로 순위 통합
통합 순위가 높은 후보부터 채택 기준을 확인한다:
  벡터 유사도 >= min_vector_score  또는  글자 겹침 비율 >= min_keyword_overlap
(두 기준값은 임베딩 모델과 실제 데이터가 정해지면 다시 맞춰야 한다)

인덱스는 처음 검색할 때 그래프 저장소의 전체 노드로 만든다.
그래프 DB 가 자체 벡터/전문 검색 인덱스를 제공하면 그 인덱스를 쓰는 구현으로 바꾸면 된다.
"""

from __future__ import annotations

import hashlib
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, fields
from typing import Any

import numpy as np

from ..paths import resolve
from ..plugins.embedder.base import Embedder
from ..plugins.graph_store.base import GraphStore, Node
from ..schemas import LinkedTarget, Mention


@dataclass
class LinkerSettings:
    top_k: int = 5  # 후보로 남길 노드 수 (01_query_plan.json 에 기록)
    rrf_k: int = 60  # RRF 상수 (보통 60)
    min_vector_score: float = 0.85
    min_keyword_overlap: float = 0.5
    include_description: bool = True  # 벡터 검색에 노드 설명도 쓸지
    cache_dir: str = "data/index"  # 노드 임베딩 캐시 위치

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> LinkerSettings:
        known = {f.name for f in fields(cls)}
        unknown = sorted(set(raw) - known)
        if unknown:
            raise ValueError(f"linker 설정에 알 수 없는 항목: {unknown} (사용 가능: {sorted(known)})")
        return cls(**raw)


class HybridLinker:
    def __init__(self, store: GraphStore, embedder: Embedder, settings: LinkerSettings) -> None:
        self.store = store
        self.embedder = embedder
        self.settings = settings
        self._index: _NodeIndex | None = None

    def link(self, mentions: list[Mention]) -> list[LinkedTarget]:
        if self._index is None:
            self._index = _NodeIndex(list(self.store.iter_nodes()), self.embedder, self.settings)
        return [self._link_one(m, self._index) for m in mentions]

    def _link_one(self, mention: Mention, index: _NodeIndex) -> LinkedTarget:
        if not index.nodes:
            return LinkedTarget(mention=mention)

        exact = index.exact.get(_norm(mention.text))
        if exact is not None:
            node = index.nodes[exact]
            return LinkedTarget(
                mention=mention, node_id=node.id, node_name=node.name, label=node.label,
                score=1.0, method="exact",
            )

        s = self.settings
        keyword_scores = index.bm25.scores(_grams(mention.text))
        vector_scores = index.vectors() @ self.embedder.embed_queries([mention.text])[0]

        pool = max(s.top_k * 4, 20)
        keyword_rank = [i for i in np.argsort(-keyword_scores) if keyword_scores[i] > 0][:pool]
        vector_rank = list(np.argsort(-vector_scores))[:pool]
        fused: dict[int, float] = defaultdict(float)
        for ranking in (keyword_rank, vector_rank):
            for rank, i in enumerate(ranking):
                fused[int(i)] += 1.0 / (s.rrf_k + rank + 1)

        candidates = []
        for i in sorted(fused, key=fused.__getitem__, reverse=True)[: s.top_k]:
            node = index.nodes[i]
            candidates.append({
                "node_id": node.id,
                "name": node.name,
                "label": node.label,
                "rrf": round(fused[i], 6),
                "vector": round(float(vector_scores[i]), 4),
                "keyword": round(float(keyword_scores[i]), 4),
                "overlap": round(index.overlap(mention.text, i), 4),
            })

        for c in candidates:
            if c["vector"] >= s.min_vector_score or c["overlap"] >= s.min_keyword_overlap:
                return LinkedTarget(
                    mention=mention, node_id=c["node_id"], node_name=c["name"], label=c["label"],
                    score=c["rrf"], method="hybrid", candidates=candidates,
                )
        return LinkedTarget(mention=mention, candidates=candidates)


class _NodeIndex:
    def __init__(self, nodes: list[Node], embedder: Embedder, settings: LinkerSettings) -> None:
        self.nodes = nodes
        self.embedder = embedder
        self.settings = settings
        self.exact: dict[str, int] = {}
        self._names: list[list[str]] = []
        for i, node in enumerate(nodes):
            names = [node.name, *node.aliases]
            self._names.append(names)
            for name in names:
                self.exact.setdefault(_norm(name), i)
        # 키워드 검색은 이름/별칭만 대상으로 한다 (설명까지 넣으면 엉뚱한 노드가 잘 걸림)
        self.bm25 = _BM25([[g for name in names for g in _grams(name)] for names in self._names])
        self._vectors: np.ndarray | None = None

    def overlap(self, text: str, i: int) -> float:
        """검색어 글자(2-gram) 중 노드 이름/별칭에 들어 있는 비율의 최댓값."""
        query = set(_grams(text))
        if not query:
            return 0.0
        return max(len(query & set(_grams(name))) / len(query) for name in self._names[i])

    def vectors(self) -> np.ndarray:
        if self._vectors is None:
            self._vectors = self._load_or_build_vectors()
        return self._vectors

    def _load_or_build_vectors(self) -> np.ndarray:
        passages = []
        for node, names in zip(self.nodes, self._names):
            text = ", ".join(names)
            if self.settings.include_description and node.description:
                text += f". {node.description}"
            passages.append(text)
        key = hashlib.sha1(
            "\n".join([self.embedder.model_id, *passages]).encode("utf-8")
        ).hexdigest()[:16]
        cache = resolve(self.settings.cache_dir) / f"nodes-{key}.npy"
        if cache.exists():
            vectors = np.load(cache)
            if vectors.shape[0] == len(passages):
                return vectors
        vectors = self.embedder.embed_passages(passages)
        cache.parent.mkdir(parents=True, exist_ok=True)
        np.save(cache, vectors)
        return vectors


class _BM25:
    def __init__(self, docs: list[list[str]], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.size = len(docs)
        self.doc_len = np.array([len(d) for d in docs], dtype=np.float64)
        self.avgdl = float(self.doc_len.mean()) if self.size and self.doc_len.sum() else 1.0
        self.postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for i, doc in enumerate(docs):
            for term, tf in Counter(doc).items():
                self.postings[term].append((i, tf))
        self.idf = {
            term: math.log(1 + (self.size - len(p) + 0.5) / (len(p) + 0.5))
            for term, p in self.postings.items()
        }

    def scores(self, query: list[str]) -> np.ndarray:
        out = np.zeros(self.size, dtype=np.float64)
        for term in set(query):
            for i, tf in self.postings.get(term, []):
                denom = tf + self.k1 * (1 - self.b + self.b * self.doc_len[i] / self.avgdl)
                out[i] += self.idf[term] * tf * (self.k1 + 1) / denom
        return out


def _norm(text: str) -> str:
    return "".join(text.lower().split())


def _grams(text: str) -> list[str]:
    s = _norm(text)
    if len(s) < 2:
        return [s] if s else []
    return [s[i : i + 2] for i in range(len(s) - 1)]
