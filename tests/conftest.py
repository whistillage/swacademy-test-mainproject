from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest

from pipeline.config import AppConfig, load_config
from pipeline.registry import PluginSpec

FIXTURES = Path(__file__).parent / "fixtures"
FROG_GRAPH = FIXTURES / "frog_graph.json"


@pytest.fixture
def make_config(tmp_path: Path) -> Callable[..., AppConfig]:
    """기본 config 를 읽고 테스트용으로 그래프/임베딩/출력 위치만 바꾼다.

    embedder 기본값은 hashing (모델 다운로드 없이 실행). 정확히 일치하는 이름으로 찾는 경우만 검증한다.
    """

    def _make(graph_path: Path = FROG_GRAPH, embedder: PluginSpec | None = None) -> AppConfig:
        config = load_config()
        config.plugins["graph_store"] = PluginSpec("json", {"path": str(graph_path)})
        config.plugins["embedder"] = embedder or PluginSpec("hashing")
        config.linker = {**config.linker, "cache_dir": str(tmp_path / "index")}
        config.output_dir = tmp_path / "output"
        return config

    return _make
