"""임베딩 모델 인터페이스 (대상 노드 찾기의 벡터 검색에 사용).

반환 벡터는 L2 정규화돼 있어야 한다 (내적 = 코사인 유사도).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

import numpy as np

from ...registry import Registry


class Embedder(ABC):
    plugin_name: ClassVar[str] = ""

    @property
    @abstractmethod
    def model_id(self) -> str:
        """임베딩 캐시 구분용 식별자. 모델이나 전처리가 바뀌면 값도 바뀌어야 한다."""

    @abstractmethod
    def embed_queries(self, texts: list[str]) -> np.ndarray:
        """검색어(요청에서 뽑은 표현) 임베딩. shape = (len(texts), dim)"""

    @abstractmethod
    def embed_passages(self, texts: list[str]) -> np.ndarray:
        """검색 대상(노드 이름/설명) 임베딩. shape = (len(texts), dim)"""


REGISTRY: Registry[Embedder] = Registry("embedder", Embedder, __package__)
register = REGISTRY.register
