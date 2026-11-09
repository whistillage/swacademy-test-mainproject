"""03 프롬프트 구성의 마지막 후처리.

이미지 모델이 영어 프롬프트를 선호하면 번역 플러그인(예: 로컬 번역 모델)을 추가해 교체한다.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from ...registry import Registry


class Translator(ABC):
    plugin_name: ClassVar[str] = ""

    @abstractmethod
    def translate(self, text: str) -> str: ...


REGISTRY: Registry[Translator] = Registry("translator", Translator, __package__)
register = REGISTRY.register
