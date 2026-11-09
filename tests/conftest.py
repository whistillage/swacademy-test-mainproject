from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest
import yaml

from pipeline.config import AppConfig, load_config
from pipeline.registry import PluginSpec

FIXTURES = Path(__file__).parent / "fixtures"
FROG_GRAPH = FIXTURES / "frog_graph.json"
MINI_MARKET = FIXTURES / "mini_market.ttl"


def _yaml(name: str) -> dict:
    return yaml.safe_load((FIXTURES / name).read_text(encoding="utf-8"))


def _base(tmp_path: Path, embedder: PluginSpec | None) -> AppConfig:
    config = load_config()
    config.plugins["embedder"] = embedder or PluginSpec("hashing")
    config.plugins["image_generator"] = PluginSpec("dummy")  # 테스트에서 GPU 모델을 불러오지 않는다
    config.linker = {**config.linker, "cache_dir": str(tmp_path / "index")}
    config.output_dir = tmp_path / "output"
    return config


@pytest.fixture
def make_config(tmp_path: Path) -> Callable[..., AppConfig]:
    """경로 탐색 방식 예시(개구리 JSON 그래프)용 config.

    embedder 기본값은 hashing (모델 다운로드 없이 실행). 정확히 일치하는 이름으로 찾는 경우만 검증한다.
    """

    def _make(graph_path: Path = FROG_GRAPH, embedder: PluginSpec | None = None) -> AppConfig:
        config = _base(tmp_path, embedder)
        config.plugins["graph_store"] = PluginSpec("json", {"path": str(graph_path)})
        config.aspects = _yaml("frog_aspects.yaml")
        config.templates = _yaml("frog_templates.yaml")
        return config

    return _make


@pytest.fixture
def make_company_config(tmp_path: Path) -> Callable[..., AppConfig]:
    """기본 config(회사 카드, SPARQL)에 테스트용 RDF 그래프만 바꾼 config."""

    def _make(graph_path: Path = MINI_MARKET) -> AppConfig:
        config = _base(tmp_path, None)
        params = dict(config.plugins["graph_store"].params)
        params["paths"] = [str(graph_path)]
        config.plugins["graph_store"] = PluginSpec("rdf", params)
        return config

    return _make
