"""속성 값 다듬기 (LLM 미사용). templates.yaml 의 values 항목.

검색 결과(Fact)를 템플릿에서 쓸 '필드 묶음'으로 바꾼다. 템플릿에서는 {속성[필드]} 로 쓴다.
  예: {yoy_growth[text]} -> "-18.7%",  {yoy_growth[arrow]} -> "▼",  {eps[date]} -> "2026-02-23"

모든 속성에 기본으로 생기는 필드
  raw     원래 값 (SPARQL 의 ?value, 또는 경로 탐색 값)
  text    표시용 문자열 (number 규칙이 있으면 그 형식)
  values  값이 여러 개일 때 text 를 value_joiner 로 이은 것
  그 외   SPARQL 결과 행의 다른 변수들 (예: ?date -> date)

규칙 (속성마다 선택)
  number: {decimals: 2, sign: false, thousands: true, prefix: "", suffix: "", clamp: null}
          clamp 를 넘는 값은 "+999%↑" / "-999%↓" 처럼 표시
  lookup: {원래 값: {필드: 값, ...}}   대응표. 예: 업종 영어 이름 -> {ko: 한글, scene: 배경 묘사}
  default: {필드: 값}                  lookup 에 없을 때 쓸 필드 ("{raw}" 를 쓸 수 있음)
  when:   [{if: ">= 0", set: {필드: 값}}, ...]   숫자 조건. 처음 맞는 것 하나만 적용
"""

from __future__ import annotations

import operator
import re
from typing import Any

from ..schemas import Fact

_OPS = {">=": operator.ge, "<=": operator.le, "==": operator.eq, "!=": operator.ne,
        ">": operator.gt, "<": operator.lt}
_CONDITION = re.compile(r"^\s*(>=|<=|==|!=|>|<)\s*(-?\d+(?:\.\d+)?)\s*$")


class Field(dict):
    """속성 하나의 필드 묶음. 없는 필드를 꺼내면 missing 문자열을 돌려준다 (템플릿이 깨지지 않도록)."""

    def __init__(self, data: dict[str, Any] | None = None, missing: str = "") -> None:
        super().__init__(data or {})
        self.missing = missing

    def __missing__(self, key: str) -> str:
        return self.missing

    def __format__(self, spec: str) -> str:  # {속성} 만 쓰면 text
        return format(self.get("text", self.missing), spec)


class Fields(dict):
    """템플릿 빈칸 전체. 없는 속성은 빈 Field (모든 필드가 missing)."""

    def __init__(self, data: dict[str, Any], missing: str = "") -> None:
        super().__init__(data)
        self.missing = missing

    def __missing__(self, key: str) -> Field:
        return Field(missing=self.missing)

    def __getitem__(self, key: str) -> Any:
        value = super().__getitem__(key) if key in self else self.__missing__(key)
        if isinstance(value, Field) and value.missing != self.missing:
            value = Field(value, missing=self.missing)
        return value


class ValueFormatter:
    def __init__(self, rules: dict[str, Any] | None, value_joiner: str = "/") -> None:
        self.rules = rules or {}
        self.value_joiner = value_joiner

    def field(self, aspect: str, facts: list[Fact]) -> Field:
        if not facts:
            return Field()
        rule = self.rules.get(aspect) or {}
        texts = [self._text(_raw(f), rule) for f in facts]
        first = facts[0]
        raw = _raw(first)
        data: dict[str, Any] = {k: _plain(v) for k, v in first.values.items()}
        data.update(raw=raw, text=texts[0], values=self.value_joiner.join(dict.fromkeys(texts)))

        extra = (rule.get("lookup") or {}).get(str(raw))
        if extra is None:
            extra = rule.get("default") or {}
        data.update({k: str(v).format(raw=raw, text=texts[0]) for k, v in extra.items()})

        number = _number(raw)
        if number is not None:
            for case in rule.get("when") or []:
                if _matches(str(case.get("if", "")), number):
                    data.update({k: str(v) for k, v in (case.get("set") or {}).items()})
                    break
        return Field(data)

    def _text(self, raw: Any, rule: dict[str, Any]) -> str:
        spec = rule.get("number")
        number = _number(raw)
        if spec is None or number is None:
            return str(_plain(raw))
        spec = {} if spec is True else spec
        prefix, suffix = str(spec.get("prefix", "")), str(spec.get("suffix", ""))
        clamp = spec.get("clamp")
        if clamp is not None and abs(number) > float(clamp):
            sign, arrow = ("+", "↑") if number > 0 else ("-", "↓")
            return f"{prefix}{sign}{_num(float(clamp), 0, spec.get('thousands', True))}{suffix}{arrow}"
        text = _num(number, int(spec.get("decimals", 2)), spec.get("thousands", True))
        if spec.get("sign") and number > 0:
            text = "+" + text
        return f"{prefix}{text}{suffix}"


def _raw(fact: Fact) -> Any:
    if "value" in fact.values:
        return fact.values["value"]
    return fact.names[-1] if fact.names else ""


def _plain(value: Any) -> Any:
    """JSON 저장과 템플릿 표시용. 날짜는 ISO 문자열로."""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", ""))
    except ValueError:
        return None


def _num(value: float, decimals: int, thousands: bool) -> str:
    return f"{value:,.{decimals}f}" if thousands else f"{value:.{decimals}f}"


def _matches(condition: str, number: float) -> bool:
    m = _CONDITION.match(condition)
    if not m:
        raise ValueError(f"templates.yaml values.*.when 조건 형식 오류: {condition!r} (예: '>= 0')")
    return _OPS[m.group(1)](number, float(m.group(2)))
