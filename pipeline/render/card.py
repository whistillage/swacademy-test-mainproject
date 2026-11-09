"""카드 글자 합성 (Pillow).

이미지 모델이 그린 배경 위에 반투명 패널을 깔고 카드 내용(PromptResult.card)을 찍는다.
숫자와 한글은 모델이 아니라 여기서 그리므로 값이 정확하다.
이미지 모델과 무관하게 동작하므로 모델을 바꿔도 이 부분은 그대로다.

카드 내용 형식 (templates.yaml 의 card 를 채운 결과)
  {"title": str, "subtitle": str, "rows": [{"label", "value", "note"?, "color"?}], "footer": str}
"""

from __future__ import annotations

import io
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

# 한글을 표시할 수 있는 폰트 후보. WSL 은 Windows 폰트 폴더(/mnt/c/...)도 찾는다.
_REGULAR_FONTS = (
    "C:/Windows/Fonts/malgun.ttf",
    "/mnt/c/Windows/Fonts/malgun.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
)
_BOLD_FONTS = (
    "C:/Windows/Fonts/malgunbd.ttf",
    "/mnt/c/Windows/Fonts/malgunbd.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
)


@dataclass
class CardStyle:
    """config.yaml 의 overlay 항목. 크기는 이미지 높이 대비 비율."""

    enabled: bool = True
    font_path: str | None = None  # 없으면 자동 탐색
    bold_font_path: str | None = None
    side: str = "left"  # 패널 위치: left | right
    panel_width: float = 0.48  # 이미지 폭 대비
    panel_color: str = "#0B1220"
    panel_opacity: float = 0.78
    text_color: str = "#F8FAFC"
    muted_color: str = "#A9B4C6"
    accent_color: str = "#F8FAFC"  # row.color 가 없을 때 값 색
    padding: float = 0.055
    title_size: float = 0.050
    subtitle_size: float = 0.027
    label_size: float = 0.024
    value_size: float = 0.050
    note_size: float = 0.019
    footer_size: float = 0.019

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> CardStyle:
        raw = dict(raw or {})
        known = {f.name for f in fields(cls)}
        unknown = sorted(set(raw) - known)
        if unknown:
            raise ValueError(f"overlay 설정에 알 수 없는 항목: {unknown} (사용 가능: {sorted(known)})")
        return cls(**raw)


class CardRenderer:
    def __init__(self, style: CardStyle) -> None:
        self.style = style
        self.regular = _find_font(style.font_path, _REGULAR_FONTS)
        self.bold = _find_font(style.bold_font_path, _BOLD_FONTS) or self.regular

    def render(self, image_bytes: bytes, card: dict[str, Any]) -> bytes:
        from PIL import Image, ImageDraw

        base = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
        w, h = base.size
        s = self.style
        panel_w = int(w * s.panel_width)
        x0 = 0 if s.side == "left" else w - panel_w
        pad = int(h * s.padding)

        overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
        ImageDraw.Draw(overlay).rectangle(
            [x0, 0, x0 + panel_w, h], fill=_rgba(s.panel_color, s.panel_opacity)
        )
        image = Image.alpha_composite(base, overlay)
        draw = ImageDraw.Draw(image)

        def font(bold: bool, ratio: float) -> Any:
            return self._font(bold, max(10, int(h * ratio)))

        left, right = x0 + pad, x0 + panel_w - pad
        width = right - left
        y = pad

        y = _text_block(draw, card.get("title", ""), left, y, width, font(True, s.title_size), s.text_color)
        y += int(h * 0.008)
        y = _text_block(draw, card.get("subtitle", ""), left, y, width, font(False, s.subtitle_size),
                        s.muted_color)
        y += int(h * 0.03)
        draw.line([left, y, right, y], fill=_rgba(s.muted_color, 0.5), width=max(1, h // 512))
        y += int(h * 0.03)

        for row in card.get("rows") or []:
            y = _text_block(draw, row.get("label", ""), left, y, width, font(False, s.label_size),
                            s.muted_color)
            color = row.get("color") or s.accent_color
            y = _text_block(draw, row.get("value", ""), left, y, width, font(True, s.value_size),
                            color if color.startswith("#") else s.accent_color)
            if row.get("note"):
                y = _text_block(draw, row["note"], left, y, width, font(False, s.note_size), s.muted_color)
            y += int(h * 0.028)

        footer = card.get("footer", "")
        if footer:
            f = font(False, s.footer_size)
            lines = _wrap(draw, footer, f, width)
            line_h = _line_height(draw, f)
            fy = max(y, h - pad - line_h * len(lines))
            draw.multiline_text((left, fy), "\n".join(lines), font=f, fill=s.muted_color,
                                spacing=int(line_h * 0.25))

        out = io.BytesIO()
        image.convert("RGB").save(out, format="PNG")
        return out.getvalue()

    def _font(self, bold: bool, size: int) -> Any:
        from PIL import ImageFont

        path = self.bold if bold else self.regular
        if path:
            return ImageFont.truetype(path, size)
        return ImageFont.load_default(size=size)


def _find_font(explicit: str | None, candidates: tuple[str, ...]) -> str | None:
    if explicit:
        if not Path(explicit).exists():
            raise FileNotFoundError(f"overlay 폰트 파일이 없습니다: {explicit}")
        return explicit
    return next((p for p in candidates if Path(p).exists()), None)


def _text_block(draw: Any, text: str, x: int, y: int, width: int, font: Any, color: str) -> int:
    """줄바꿈해서 그리고 다음 y 를 돌려준다."""
    if not text:
        return y
    lines = _wrap(draw, text, font, width)
    line_h = _line_height(draw, font)
    spacing = int(line_h * 0.2)
    draw.multiline_text((x, y), "\n".join(lines), font=font, fill=color, spacing=spacing)
    return y + line_h * len(lines) + spacing * (len(lines) - 1) + spacing


def _line_height(draw: Any, font: Any) -> int:
    box = draw.textbbox((0, 0), "가Ag", font=font)
    return box[3] - box[1]


def _wrap(draw: Any, text: str, font: Any, max_width: int) -> list[str]:
    """단어 단위로 줄바꿈하고, 한 단어가 폭보다 길면 글자 단위로 자른다."""
    lines: list[str] = []
    for paragraph in str(text).split("\n"):
        line = ""
        for word in paragraph.split(" "):
            candidate = f"{line} {word}" if line else word
            if draw.textlength(candidate, font=font) <= max_width:
                line = candidate
                continue
            if line:
                lines.append(line)
            line = ""
            for ch in word:
                if line and draw.textlength(line + ch, font=font) > max_width:
                    lines.append(line)
                    line = ch
                else:
                    line += ch
        lines.append(line)
    return lines


def _rgba(color: str, opacity: float) -> tuple[int, int, int, int]:
    c = color.lstrip("#")
    r, g, b = (int(c[i : i + 2], 16) for i in (0, 2, 4))
    return r, g, b, int(255 * max(0.0, min(1.0, opacity)))
