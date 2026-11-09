"""설정 로드.

- config/config.yaml : 어떤 플러그인을 쓸지와 단계별 설정
- aspects / templates / lexicon : config.yaml 의 files 항목이 가리키는 YAML
- 문자열 안의 ${ENV_VAR} 또는 ${ENV_VAR:-기본값} 은 환경변수(.env 포함)로 치환된다.
  API 키는 config 에 직접 쓰지 말고 .env 에 두고 ${...} 로 참조한다.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from .paths import PROJECT_ROOT, resolve
from .registry import PluginError, PluginSpec

DEFAULT_CONFIG = PROJECT_ROOT / "config" / "config.yaml"

# config.yaml 에서 플러그인으로 지정하는 항목 (= 교체 가능한 구성요소)
PLUGIN_SECTIONS = ("graph_store", "embedder", "request_parser", "translator", "image_generator")

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


class ConfigError(ValueError):
    """설정 파일이 없거나 형식이 잘못됐을 때."""


@dataclass
class AppConfig:
    plugins: dict[str, PluginSpec]
    linker: dict[str, Any]
    generation: dict[str, Any]
    aspects: dict[str, Any]
    templates: dict[str, Any]
    lexicon: dict[str, Any]
    output_dir: Path
    source: Path
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


def load_config(path: str | Path | None = None) -> AppConfig:
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    config_path = resolve(path) if path else DEFAULT_CONFIG
    raw = _expand_env(_read_yaml(config_path))

    plugins: dict[str, PluginSpec] = {}
    for section in PLUGIN_SECTIONS:
        if section not in raw:
            raise ConfigError(f"{config_path}: '{section}' 항목이 없습니다.")
        try:
            plugins[section] = PluginSpec.parse(raw[section], section)
        except PluginError as exc:
            raise ConfigError(f"{config_path}: {exc}") from exc

    files = raw.get("files") or {}

    def load_side_file(key: str) -> dict[str, Any]:
        if key not in files:
            raise ConfigError(f"{config_path}: files.{key} 항목이 없습니다.")
        return _expand_env(_read_yaml(resolve(files[key])))

    return AppConfig(
        plugins=plugins,
        linker=dict(raw.get("linker") or {}),
        generation=dict(raw.get("generation") or {}),
        aspects=load_side_file("aspects"),
        templates=load_side_file("templates"),
        lexicon=load_side_file("lexicon"),
        output_dir=resolve(raw.get("output_dir", "output")),
        source=config_path,
        raw=raw,
    )


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"설정 파일이 없습니다: {path}")
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: 최상위는 key-value 형태여야 합니다.")
    return data


def _expand_env(value: Any) -> Any:
    if isinstance(value, str):
        return _ENV_PATTERN.sub(lambda m: os.environ.get(m.group(1), m.group(2) or ""), value)
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    return value
