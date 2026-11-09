"""이미지 생성 모델 인터페이스 (04 이미지 생성).

새 모델을 붙이는 방법
  1. 이 폴더의 _template.py 를 복사해 새 파일로 저장 (예: my_model.py)
  2. ImageGenerator 를 상속해 generate() 를 구현하고 @register("이름") 을 붙인다
  3. config.yaml 의 image_generator.name 을 그 이름으로 바꾼다
파이프라인의 다른 코드는 수정하지 않는다.

플러그인이 하는 일은 "ImageRequest -> 이미지 bytes" 뿐이다.
프롬프트 구성, 파일 저장, 실행 기록은 파이프라인이 처리한다.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar

from ...registry import Registry


@dataclass
class ImageRequest:
    """모델과 무관한 공통 요청 (값은 config.yaml 의 generation 항목).

    모델이 지원하지 않는 값은 플러그인이 무시하거나 가장 가까운 값으로 바꾸고,
    그 사실을 GenerationResult.metadata 에 남긴다.
    """

    prompt: str
    negative_prompt: str = ""
    width: int = 1024
    height: int = 1024
    num_images: int = 1
    seed: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)  # 특정 모델 전용 옵션 (generation.extra)


@dataclass
class GeneratedImage:
    data: bytes  # PNG / JPEG / WEBP 바이트
    mime_type: str = "image/png"


@dataclass
class GenerationResult:
    images: list[GeneratedImage]
    model: str  # 실제로 사용한 모델 이름/버전
    metadata: dict[str, Any] = field(default_factory=dict)  # 실제 seed, 무시한 옵션 등


class ImageGenerator(ABC):
    plugin_name: ClassVar[str] = ""

    @abstractmethod
    def generate(self, request: ImageRequest) -> GenerationResult: ...

    def close(self) -> None:
        """모델 메모리 해제, 세션 종료 등. 기본은 아무것도 하지 않는다."""


REGISTRY: Registry[ImageGenerator] = Registry("image_generator", ImageGenerator, __package__)
register = REGISTRY.register
