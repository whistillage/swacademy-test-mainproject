"""새 이미지 생성 모델 플러그인 템플릿.

파일 이름이 _ 로 시작하므로 이 파일 자체는 자동 등록되지 않는다.

사용법
  1. 이 파일을 복사해 새 이름으로 저장 (예: my_model.py)
  2. 클래스 이름과 @register("...") 이름을 바꾸고 generate() 를 구현
  3. config/config.yaml 수정
       image_generator:
         name: my_model
         params:
           api_key: ${MY_MODEL_API_KEY}   # 실제 값은 .env 에 저장
           model: some-model-version
  4. python run.py --list-plugins 로 등록됐는지 확인
     (등록이 안 되면 같은 명령이 import 오류를 보여준다)

지켜야 할 것
  - 무거운 라이브러리(torch, diffusers, 각종 SDK)는 파일 맨 위가 아니라 __init__ 또는 generate 안에서 import.
    그래야 다른 모델을 쓸 때 그 라이브러리가 설치돼 있지 않아도 문제가 없다.
  - 결과는 이미지 bytes 로 돌려준다. 파일 저장은 파이프라인이 한다.
  - ImageRequest 의 값 중 모델이 지원하지 않는 것(negative_prompt, seed 등)은 무시하고 metadata 에 기록한다.
  - 모델 전용 옵션은 config.yaml 의 generation.extra 로 받는다 (request.extra).
"""

from __future__ import annotations

from .base import GeneratedImage, GenerationResult, ImageGenerator, ImageRequest, register


@register("my_model")  # <- 이름 변경
class MyModelGenerator(ImageGenerator):  # <- 클래스 이름 변경
    def __init__(self, api_key: str = "", model: str = "") -> None:
        if not api_key:
            raise ValueError("api_key 가 비어 있습니다. .env 와 config.yaml 을 확인하세요.")
        self.api_key = api_key
        self.model = model
        # 예) API 클라이언트 / 로컬 모델 로드
        # from some_sdk import Client
        # self.client = Client(api_key=api_key)

    def generate(self, request: ImageRequest) -> GenerationResult:
        # 예) API 호출
        # response = self.client.generate(
        #     model=self.model,
        #     prompt=request.prompt,
        #     size=f"{request.width}x{request.height}",
        #     n=request.num_images,
        # )
        # images = [GeneratedImage(data=item.image_bytes, mime_type="image/png") for item in response]
        # return GenerationResult(
        #     images=images,
        #     model=self.model,
        #     metadata={"ignored": ["negative_prompt", "seed"]},
        # )
        raise NotImplementedError

    def close(self) -> None:
        # 예) 로컬 모델이면 GPU 메모리 해제
        pass


# 아래 이름들은 구현할 때 쓰도록 import 해 둔 것 (린터 경고 방지용)
__all__ = ["GeneratedImage", "GenerationResult", "ImageRequest", "MyModelGenerator"]
