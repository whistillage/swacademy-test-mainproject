"""플러그인 레지스트리.

아직 정해지지 않은 구성요소(그래프 DB, 임베딩 모델, 이미지 생성 모델 등)를
코드 수정 없이 config.yaml 만 바꿔 교체하기 위한 장치.

config.yaml 에서 플러그인을 지정하는 두 가지 방법
  1) 등록 이름     name: dummy
     pipeline/plugins/<category>/ 아래 모듈을 자동으로 import 해서
     @register("dummy") 로 등록된 클래스를 찾는다.
  2) import 경로  name: my_pkg.my_module:MyClass
     프로젝트 밖에 있는 클래스도 등록 없이 바로 쓸 수 있다.
"""

from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass, field
from typing import Any, Callable, Generic, TypeVar

T = TypeVar("T")


class PluginError(RuntimeError):
    """플러그인을 찾거나 생성하지 못했을 때."""


@dataclass
class PluginSpec:
    """config.yaml 의 플러그인 항목: 어떤 플러그인(name)을 어떤 설정(params)으로 쓸지."""

    name: str
    params: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def parse(cls, raw: Any, where: str) -> PluginSpec:
        if isinstance(raw, str):
            return cls(name=raw)
        if isinstance(raw, dict) and isinstance(raw.get("name"), str):
            params = raw.get("params") or {}
            if not isinstance(params, dict):
                raise PluginError(f"{where}.params 는 key-value 형태여야 합니다.")
            return cls(name=raw["name"], params=dict(params))
        raise PluginError(f"{where} 에는 'name' 이 필요합니다. 현재 값: {raw!r}")


class Registry(Generic[T]):
    """카테고리 하나(예: image_generator)의 플러그인 목록."""

    def __init__(self, category: str, base: type[T], package: str) -> None:
        self.category = category
        self.base = base
        self.package = package
        self._plugins: dict[str, type[T]] = {}
        self._import_errors: dict[str, str] = {}
        self._discovered = False

    def register(self, name: str) -> Callable[[type[T]], type[T]]:
        """클래스 데코레이터: @register("이름")."""

        def decorator(cls: type[T]) -> type[T]:
            if not (isinstance(cls, type) and issubclass(cls, self.base)):
                raise PluginError(f"{cls!r} 는 {self.base.__name__} 를 상속해야 합니다.")
            existing = self._plugins.get(name)
            if existing is not None and _qualname(existing) != _qualname(cls):
                raise PluginError(
                    f"'{self.category}/{name}' 이름이 이미 {_qualname(existing)} 에 등록돼 있습니다."
                )
            self._plugins[name] = cls
            cls.plugin_name = name  # type: ignore[attr-defined]
            return cls

        return decorator

    def names(self) -> list[str]:
        self._discover()
        return sorted(self._plugins)

    @property
    def import_errors(self) -> dict[str, str]:
        """자동 탐색 중 import 에 실패한 플러그인 모듈과 그 이유."""
        self._discover()
        return dict(self._import_errors)

    def get(self, name: str) -> type[T]:
        if ":" in name:
            return self._load_path(name)
        self._discover()
        if name in self._plugins:
            return self._plugins[name]
        message = (
            f"'{self.category}' 플러그인 '{name}' 을 찾을 수 없습니다. "
            f"사용 가능: {', '.join(self.names()) or '(없음)'}"
        )
        if self._import_errors:
            details = "; ".join(f"{m} -> {e}" for m, e in self._import_errors.items())
            message += f"\n불러오지 못한 플러그인 모듈: {details}"
        raise PluginError(message)

    def create(self, spec: PluginSpec, **dependencies: Any) -> T:
        """spec.params 와 파이프라인이 넘겨주는 의존성(dependencies)으로 인스턴스를 만든다."""
        cls = self.get(spec.name)
        try:
            return cls(**spec.params, **dependencies)
        except TypeError as exc:
            raise PluginError(
                f"'{self.category}/{spec.name}' 생성 실패 (config 의 params 를 확인하세요): {exc}"
            ) from exc

    def _discover(self) -> None:
        if self._discovered:
            return
        package = importlib.import_module(self.package)
        for info in pkgutil.iter_modules(package.__path__):
            # base.py(인터페이스)와 _ 로 시작하는 파일(예: _template.py)은 플러그인이 아니다.
            if info.name == "base" or info.name.startswith("_"):
                continue
            module_name = f"{self.package}.{info.name}"
            try:
                importlib.import_module(module_name)
            except Exception as exc:  # 플러그인 하나의 문제로 전체가 멈추지 않도록 기록만 한다.
                self._import_errors[module_name] = f"{type(exc).__name__}: {exc}"
        self._discovered = True

    def _load_path(self, path: str) -> type[T]:
        module_name, _, attr = path.partition(":")
        try:
            obj = getattr(importlib.import_module(module_name), attr)
        except (ImportError, AttributeError) as exc:
            raise PluginError(f"'{path}' 를 불러올 수 없습니다: {exc}") from exc
        if not (isinstance(obj, type) and issubclass(obj, self.base)):
            raise PluginError(f"'{path}' 는 {self.base.__name__} 를 상속한 클래스가 아닙니다.")
        return obj


def _qualname(cls: type) -> str:
    return f"{cls.__module__}.{cls.__qualname__}"
