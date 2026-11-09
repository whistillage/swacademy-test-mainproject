from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from pipeline.plugins import IMAGE_GENERATORS, REGISTRIES
from pipeline.plugins.image_generator.base import GenerationResult, ImageGenerator, ImageRequest
from pipeline.registry import PluginError, PluginSpec, Registry
from pipeline.runner import Pipeline


def test_builtin_plugins_are_discovered():
    names = {category: registry.names() for category, registry in REGISTRIES.items()}
    assert names["graph_store"] == ["json"]
    assert names["image_generator"] == ["dummy"]  # _template.py 는 등록되지 않는다
    assert {"kiwi", "simple"} <= set(names["request_parser"])
    assert {"hashing", "sentence_transformers"} <= set(names["embedder"])
    assert all(not r.import_errors for r in REGISTRIES.values())


def test_unknown_plugin_lists_available_names():
    with pytest.raises(PluginError, match="사용 가능: dummy"):
        IMAGE_GENERATORS.get("no_such_model")


def test_wrong_params_give_clear_error():
    with pytest.raises(PluginError, match="params"):
        IMAGE_GENERATORS.create(PluginSpec("dummy", {"not_a_param": 1}))


def test_duplicate_name_is_rejected():
    registry: Registry[ImageGenerator] = Registry("t", ImageGenerator, "pipeline.plugins.image_generator")

    @registry.register("same")
    class A(ImageGenerator):
        def generate(self, request: ImageRequest) -> GenerationResult:
            raise NotImplementedError

    with pytest.raises(PluginError, match="이미"):

        @registry.register("same")
        class B(ImageGenerator):
            def generate(self, request: ImageRequest) -> GenerationResult:
                raise NotImplementedError


def test_external_generator_swaps_in_by_config_only(make_config, tmp_path: Path, monkeypatch):
    """프로젝트 코드 수정 없이 config 의 name 만으로 이미지 모델을 교체할 수 있는지."""
    (tmp_path / "my_plugins.py").write_text(
        textwrap.dedent(
            """
            from pipeline.plugins.image_generator.base import (
                GeneratedImage, GenerationResult, ImageGenerator, ImageRequest,
            )

            class EchoGenerator(ImageGenerator):
                def __init__(self, tag: str = "") -> None:
                    self.tag = tag

                def generate(self, request: ImageRequest) -> GenerationResult:
                    data = f"{self.tag}|{request.prompt}".encode("utf-8")
                    return GenerationResult(
                        images=[GeneratedImage(data=data, mime_type="image/png")],
                        model="echo",
                        metadata={"width": request.width},
                    )
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    config = make_config()
    config.plugins["image_generator"] = PluginSpec("my_plugins:EchoGenerator", {"tag": "T"})
    pipeline = Pipeline(config)
    record = pipeline.run("개구리를 그려줘")

    assert record.image_paths[0].read_bytes().decode("utf-8") == f"T|{record.prompt.positive}"
