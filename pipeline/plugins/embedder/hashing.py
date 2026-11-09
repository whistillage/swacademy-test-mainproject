"""모델 다운로드 없이 동작하는 문자 n-gram 해싱 임베딩.

테스트와 오프라인 확인용. 글자가 겹치는 정도만 반영하고 의미는 반영하지 못한다.
"""

from __future__ import annotations

import hashlib

import numpy as np

from .base import Embedder, register


@register("hashing")
class HashingEmbedder(Embedder):
    def __init__(self, dim: int = 512, min_n: int = 1, max_n: int = 3) -> None:
        self.dim = dim
        self.min_n = min_n
        self.max_n = max_n

    @property
    def model_id(self) -> str:
        return f"hashing:{self.dim}:{self.min_n}-{self.max_n}"

    def embed_queries(self, texts: list[str]) -> np.ndarray:
        return self._embed(texts)

    def embed_passages(self, texts: list[str]) -> np.ndarray:
        return self._embed(texts)

    def _embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        return np.stack([self._embed_one(t) for t in texts])

    def _embed_one(self, text: str) -> np.ndarray:
        vec = np.zeros(self.dim, dtype=np.float32)
        s = text.lower().strip()
        for n in range(self.min_n, self.max_n + 1):
            for i in range(len(s) - n + 1):
                gram = s[i : i + n]
                if gram.isspace():
                    continue
                h = int.from_bytes(hashlib.md5(gram.encode("utf-8")).digest()[:4], "little")
                vec[h % self.dim] += 1.0
        norm = float(np.linalg.norm(vec))
        return vec / norm if norm else vec
