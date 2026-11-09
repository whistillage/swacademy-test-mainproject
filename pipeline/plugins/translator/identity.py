"""번역하지 않고 그대로 둔다 (기본값)."""

from __future__ import annotations

from .base import Translator, register


@register("identity")
class IdentityTranslator(Translator):
    def translate(self, text: str) -> str:
        return text
