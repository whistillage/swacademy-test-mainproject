"""파이프라인 조립과 순차 실행.

요청 -> 01 쿼리 구성 -> 02 GraphRAG 검색 -> 03 프롬프트 구성 -> 04 이미지 생성

각 단계 결과는 output/<실행시각>/ 에 저장된다.
  00_request.txt      요청 원문
  01_query_plan.json  요청 분석, 대상 노드, 속성별 쿼리
  02_retrieval.json   속성별 검색 결과
  03_prompt.json      최종 프롬프트와 각 값의 출처
  04_background*.png  이미지 모델이 그린 원본 (카드 글자를 합성할 때만)
  04_image*.png       최종 이미지 (카드가 있으면 글자 합성 결과)
  04_generation.json  이미지 모델 요청/응답 정보
  run.json            사용한 플러그인, 단계별 소요 시간, 오류
중간에 실패해도 그때까지의 결과와 run.json(오류 포함)은 남는다.
"""

from __future__ import annotations

import json
import time
import traceback
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import AppConfig
from .plugins import EMBEDDERS, GRAPH_STORES, IMAGE_GENERATORS, REQUEST_PARSERS, TRANSLATORS
from .plugins.image_generator.base import GeneratedImage, ImageRequest
from .prompt.builder import PromptBuilder
from .query.builder import QueryBuilder
from .query.lexicon import Lexicon
from .query.linker import HybridLinker, LinkerSettings
from .query.planner import AspectCatalog, QueryPlanner
from .render.card import CardRenderer, CardStyle
from .retrieval.executor import QueryExecutor
from .schemas import PromptResult, QueryPlan, RetrievalResult

_EXTENSIONS = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}
_SECRET_HINTS = ("key", "token", "secret", "password")


@dataclass
class RunRecord:
    run_dir: Path
    plan: QueryPlan
    retrieval: RetrievalResult
    prompt: PromptResult
    image_paths: list[Path]


class Pipeline:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        specs = config.plugins
        catalog = AspectCatalog(config.aspects)

        self.store = GRAPH_STORES.create(specs["graph_store"])
        linker = HybridLinker(
            self.store,
            EMBEDDERS.create(specs["embedder"]),
            LinkerSettings.from_dict(config.linker),
        )
        parser = REQUEST_PARSERS.create(specs["request_parser"], lexicon=Lexicon(config.lexicon))

        self.query_builder = QueryBuilder(parser, linker, QueryPlanner(catalog))
        self.executor = QueryExecutor(self.store, catalog)
        self.prompt_builder = PromptBuilder(config.templates, catalog, TRANSLATORS.create(specs["translator"]))
        self.generator = IMAGE_GENERATORS.create(specs["image_generator"])
        style = CardStyle.from_dict(config.overlay)
        self.card_renderer = CardRenderer(style) if style.enabled else None

    def run(self, request: str, output_dir: Path | None = None) -> RunRecord:
        run_dir = _new_run_dir(output_dir or self.config.output_dir)
        timings: dict[str, float] = {}
        info: dict[str, Any] = {
            "request": request,
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "config": str(self.config.source),
            "plugins": {
                section: {"name": spec.name, "params": _redact(spec.params)}
                for section, spec in self.config.plugins.items()
            },
            "timings_sec": timings,
        }
        try:
            _write_text(run_dir / "00_request.txt", request)

            with _timer(timings, "01_query"):
                plan = self.query_builder.build(request)
            _write_json(run_dir / "01_query_plan.json", plan.to_dict())

            with _timer(timings, "02_retrieval"):
                retrieval = self.executor.execute(plan)
            _write_json(run_dir / "02_retrieval.json", retrieval.to_dict())

            with _timer(timings, "03_prompt"):
                prompt = self.prompt_builder.build(plan, retrieval)
            _write_json(run_dir / "03_prompt.json", prompt.to_dict())

            image_request = self._image_request(prompt)
            with _timer(timings, "04_image"):
                generation = self.generator.generate(image_request)
            images = generation.images
            overlay = bool(prompt.card and self.card_renderer)
            if overlay:
                assert self.card_renderer is not None
                _save_images(run_dir, images, "04_background")
                with _timer(timings, "04_overlay"):
                    images = [
                        GeneratedImage(self.card_renderer.render(img.data, prompt.card), "image/png")
                        for img in images
                    ]
            image_paths = _save_images(run_dir, images)
            _write_json(run_dir / "04_generation.json", {
                "request": asdict(image_request),
                "model": generation.model,
                "metadata": generation.metadata,
                "card_overlay": overlay,
                "files": [p.name for p in image_paths],
            })
        except Exception as exc:
            info["error"] = {"type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()}
            raise
        finally:
            _write_json(run_dir / "run.json", info)

        return RunRecord(run_dir, plan, retrieval, prompt, image_paths)

    def close(self) -> None:
        self.generator.close()
        self.store.close()

    def _image_request(self, prompt: PromptResult) -> ImageRequest:
        g = self.config.generation
        seed = g.get("seed")
        return ImageRequest(
            prompt=prompt.positive,
            negative_prompt=prompt.negative,
            width=int(g.get("width", 1024)),
            height=int(g.get("height", 1024)),
            num_images=int(g.get("num_images", 1)),
            seed=None if seed in (None, "") else int(seed),
            extra=dict(g.get("extra") or {}),
        )


def _new_run_dir(root: Path) -> Path:
    base = root / datetime.now().strftime("%Y%m%d-%H%M%S")
    candidate, n = base, 2
    while candidate.exists():
        candidate = base.with_name(f"{base.name}-{n}")
        n += 1
    candidate.mkdir(parents=True)
    return candidate


def _save_images(run_dir: Path, images: list[Any], stem: str = "04_image") -> list[Path]:
    paths = []
    for i, image in enumerate(images, start=1):
        suffix = "" if len(images) == 1 else f"_{i}"
        path = run_dir / f"{stem}{suffix}{_EXTENSIONS.get(image.mime_type, '.bin')}"
        path.write_bytes(image.data)
        paths.append(path)
    return paths


@contextmanager
def _timer(timings: dict[str, float], name: str) -> Iterator[None]:
    start = time.perf_counter()
    try:
        yield
    finally:
        timings[name] = round(time.perf_counter() - start, 3)


def _redact(params: dict[str, Any]) -> dict[str, Any]:
    """run.json 에 API 키가 남지 않도록 가린다."""
    return {
        k: ("***" if v and any(h in k.lower() for h in _SECRET_HINTS) else v)
        for k, v in params.items()
    }


def _write_text(path: Path, text: str) -> None:
    path.write_text(text + "\n", encoding="utf-8")


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
