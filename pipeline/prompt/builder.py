"""03 프롬프트 구성: 템플릿 조합 (LLM 미사용).

config/templates.yaml 의 빈칸에 쿼리/검색 결과를 채운다.
  - 사용자가 요청에 직접 쓴 속성이 그래프 값보다 우선한다
  - 그래프에서 못 찾은 대상은 요청에 나온 표현 그대로 쓴다
  - 마지막에 translator 플러그인으로 후처리한다 (기본: 그대로)
"""

from __future__ import annotations

import re
from typing import Any

from ..plugins.translator.base import Translator
from ..query.planner import AspectCatalog
from ..schemas import AspectResult, Fact, LinkedTarget, PromptResult, QueryPlan, RetrievalResult


class _SafeDict(dict):
    """템플릿에 정의되지 않은 빈칸이 있어도 오류 대신 빈 문자열로 둔다."""

    def __missing__(self, key: str) -> str:
        return ""


class PromptBuilder:
    def __init__(self, templates: dict[str, Any], catalog: AspectCatalog, translator: Translator) -> None:
        self.prompt_cfg = templates.get("prompt") or {}
        self.target_cfg = templates.get("target") or {}
        self.aspect_cfg = templates.get("aspect") or {}
        self.catalog = catalog
        self.translator = translator

    def build(self, plan: QueryPlan, retrieval: RetrievalResult) -> PromptResult:
        results = {(r.target_id, r.aspect): r for r in retrieval.results}
        target_texts: list[str] = []
        slots: list[dict[str, Any]] = []
        for target in plan.targets:
            text, slot = self._describe_target(target, results)
            target_texts.append(text)
            slots.append(slot)

        fields = _SafeDict(request=plan.request, style=self.prompt_cfg.get("style", ""))
        if target_texts:
            fields["targets"] = self.target_cfg.get("target_joiner", ", ").join(target_texts)
        else:  # 요청에서 대상을 하나도 못 찾았을 때
            fields["targets"] = self.prompt_cfg.get("fallback_targets", "{request}").format_map(fields)
        if plan.parsed.unassigned_attributes:
            fields["attributes"] = self.target_cfg.get("attribute_joiner", ", ").join(
                self._format_aspect(a, v) for a, v in plan.parsed.unassigned_attributes.items()
            )

        source_positive = _tidy(self.prompt_cfg.get("positive", "{targets}").format_map(fields))
        source_negative = _tidy(self.prompt_cfg.get("negative", ""))
        return PromptResult(
            positive=self.translator.translate(source_positive),
            negative=self.translator.translate(source_negative) if source_negative else "",
            source_positive=source_positive,
            source_negative=source_negative,
            slots=slots,
        )

    def _describe_target(
        self, target: LinkedTarget, results: dict[tuple[str, str], AspectResult]
    ) -> tuple[str, dict[str, Any]]:
        user = target.mention.attributes
        order = [spec.name for spec in self.catalog.aspects_for(target.label)] if target.linked else []
        order += [a for a in user if a not in order]

        phrases: list[str] = []
        aspects: dict[str, Any] = {}
        for aspect in order:
            if aspect in user:
                values, source = list(user[aspect]), "user"
            else:
                result = results.get((str(target.node_id), aspect))
                if result is None or result.status == "missing":
                    aspects[aspect] = {"values": [], "source": "missing"}
                    continue
                values = [self._render_fact(f) for f in result.facts]
                source = result.status if result.status == "found" else f"inherited:{result.source_id}"
            aspects[aspect] = {"values": values, "source": source}
            phrases.append(self._format_aspect(aspect, values))

        subject = target.node_name if target.linked else target.mention.text
        template_key = "with_attributes" if phrases else "without_attributes"
        default = "{subject}({attributes})" if phrases else "{subject}"
        text = self.target_cfg.get(template_key, default).format_map(_SafeDict(
            subject=subject,
            attributes=self.target_cfg.get("attribute_joiner", ", ").join(phrases),
        ))
        slot = {
            "mention": target.mention.text,
            "node_id": target.node_id,
            "subject": subject,
            "linked": target.linked,
            "aspects": aspects,
        }
        return text, slot

    def _format_aspect(self, aspect: str, values: list[str]) -> str:
        formats = self.aspect_cfg.get("formats") or {}
        template = formats.get(aspect, formats.get("_default", "{values}"))
        unique = list(dict.fromkeys(values))
        joined = self.aspect_cfg.get("value_joiner", "/").join(unique)
        return template.format_map(_SafeDict(aspect=aspect, values=joined))

    def _render_fact(self, fact: Fact) -> str:
        """2-hop 이상 경로는 path_format 으로 표기. 예: ["뒷다리", "길다"] -> "뒷다리(길다)" """
        if len(fact.names) == 1:
            return fact.names[0]
        rest = self.aspect_cfg.get("path_joiner", " ").join(fact.names[1:])
        return self.aspect_cfg.get("path_format", "{head}({rest})").format_map(
            _SafeDict(head=fact.names[0], rest=rest)
        )


def _tidy(text: str) -> str:
    """빈칸이 비어서 생긴 공백/구두점 정리."""
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\(\s*\)", "", text)
    text = re.sub(r"\s+([,.)])", r"\1", text)
    # 연속된 구두점은 마지막 것만 남긴다. 예: "개구리, . 일러스트" -> "개구리. 일러스트"
    text = re.sub(r"[,.](?:\s*[,.])+", lambda m: m.group(0)[-1], text)
    return text.strip(" ,.")
