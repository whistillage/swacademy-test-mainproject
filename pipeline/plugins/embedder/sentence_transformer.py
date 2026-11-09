"""sentence-transformers 로 불러오는 로컬 임베딩 모델 (무료, 처음 사용할 때 다운로드).

모델별 접두어 설정 (config.yaml 의 embedder.params)
  intfloat/multilingual-e5-*  : query_prefix "query: ", passage_prefix "passage: "
  BAAI/bge-m3                 : 둘 다 ""
"""

from __future__ import annotations

from typing import Any

import numpy as np

from .base import Embedder, register


@register("sentence_transformers")
class SentenceTransformerEmbedder(Embedder):
    def __init__(
        self,
        model_name: str = "intfloat/multilingual-e5-small",
        query_prefix: str = "query: ",
        passage_prefix: str = "passage: ",
        device: str = "cpu",
        batch_size: int = 32,
    ) -> None:
        self.model_name = model_name
        self.query_prefix = query_prefix
        self.passage_prefix = passage_prefix
        self.device = device
        self.batch_size = batch_size
        # 실제로 필요할 때 로드한다. 그래프가 비어 있으면 모델 다운로드도 일어나지 않는다.
        self._model: Any = None

    @property
    def model_id(self) -> str:
        return f"st:{self.model_name}|q={self.query_prefix}|p={self.passage_prefix}"

    def embed_queries(self, texts: list[str]) -> np.ndarray:
        return self._encode([self.query_prefix + t for t in texts])

    def embed_passages(self, texts: list[str]) -> np.ndarray:
        return self._encode([self.passage_prefix + t for t in texts])

    def _encode(self, texts: list[str]) -> np.ndarray:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name, device=self.device)
        vectors = self._model.encode(
            texts,
            batch_size=self.batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return np.asarray(vectors, dtype=np.float32)
