"""실제 모델 없이 프롬프트를 적은 자리표시 이미지를 만든다 (파이프라인 확인용, 기본값)."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from .base import GeneratedImage, GenerationResult, ImageGenerator, ImageRequest, register

# 한글을 표시할 수 있는 폰트 후보 (없으면 Pillow 기본 폰트 -> 한글은 깨질 수 있음)
_FONT_CANDIDATES = (
    "C:/Windows/Fonts/malgun.ttf",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
)


@register("dummy")
class DummyImageGenerator(ImageGenerator):
    def __init__(
        self,
        background: str = "#E8EEF7",
        foreground: str = "#1F2A44",
        font_path: str | None = None,
        font_size: int = 28,
        margin: int = 48,
    ) -> None:
        self.background = background
        self.foreground = foreground
        self.font_path = font_path
        self.font_size = font_size
        self.margin = margin

    def generate(self, request: ImageRequest) -> GenerationResult:
        from PIL import Image, ImageDraw

        font = self._load_font()
        count = max(1, request.num_images)
        images: list[GeneratedImage] = []
        for i in range(count):
            image = Image.new("RGB", (request.width, request.height), self.background)
            draw = ImageDraw.Draw(image)
            text = f"[dummy {i + 1}/{count}]\n\n{request.prompt}"
            if request.negative_prompt:
                text += f"\n\n(negative) {request.negative_prompt}"
            wrapped = _wrap(text, draw, font, request.width - 2 * self.margin)
            draw.multiline_text(
                (self.margin, self.margin), wrapped, fill=self.foreground, font=font, spacing=10
            )
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            images.append(GeneratedImage(data=buffer.getvalue(), mime_type="image/png"))
        return GenerationResult(
            images=images,
            model="dummy",
            metadata={"note": "자리표시 이미지 (실제 생성 모델 아님)", "seed_ignored": request.seed},
        )

    def _load_font(self) -> Any:
        from PIL import ImageFont

        candidates = [self.font_path] if self.font_path else []
        candidates += [p for p in _FONT_CANDIDATES if Path(p).exists()]
        for path in candidates:
            try:
                return ImageFont.truetype(path, self.font_size)
            except OSError:
                continue
        return ImageFont.load_default(size=self.font_size)


def _wrap(text: str, draw: Any, font: Any, max_width: int) -> str:
    """글자 단위 줄바꿈 (띄어쓰기가 적은 한국어 문장도 폭에 맞춘다)."""
    lines: list[str] = []
    for paragraph in text.split("\n"):
        line = ""
        for ch in paragraph:
            if line and draw.textlength(line + ch, font=font) > max_width:
                lines.append(line)
                line = ch.lstrip()
            else:
                line += ch
        lines.append(line)
    return "\n".join(lines)
