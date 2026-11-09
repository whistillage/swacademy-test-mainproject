"""CLI 진입점.

  python run.py "빨간 개구리를 그려줘"
  python run.py "개구리를 그려줘" --image-generator dummy
  python run.py --list-plugins
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pipeline.config import ConfigError, load_config
from pipeline.plugins import REGISTRIES
from pipeline.plugins.graph_store.base import GraphDataError
from pipeline.registry import PluginError, PluginSpec
from pipeline.runner import Pipeline, RunRecord


def main(argv: list[str] | None = None) -> int:
    _use_utf8_console()
    parser = argparse.ArgumentParser(description="GraphRAG 기반 이미지 생성 파이프라인")
    parser.add_argument("request", nargs="?", help="이미지 요청 문장")
    parser.add_argument("--config", help="설정 파일 경로 (기본: config/config.yaml)")
    parser.add_argument(
        "--image-generator",
        metavar="NAME",
        help="이번 실행에만 쓸 이미지 생성 플러그인 (params 없이 생성됨)",
    )
    parser.add_argument("--output-dir", help="결과 저장 폴더 (기본: config 의 output_dir)")
    parser.add_argument("--list-plugins", action="store_true", help="등록된 플러그인 목록 출력")
    args = parser.parse_args(argv)

    if args.list_plugins:
        _print_plugins()
        return 0
    if not args.request:
        parser.error("요청 문장을 입력하세요. 예: python run.py \"개구리를 그려줘\"")

    try:
        config = load_config(args.config)
        if args.image_generator:
            config.plugins["image_generator"] = PluginSpec(args.image_generator)
        pipeline = Pipeline(config)
        try:
            record = pipeline.run(args.request, Path(args.output_dir) if args.output_dir else None)
        finally:
            pipeline.close()
    except (ConfigError, PluginError, GraphDataError, FileNotFoundError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1

    _print_summary(record)
    return 0


def _print_summary(record: RunRecord) -> None:
    print(f"결과 폴더: {record.run_dir}")
    print("\n[01 쿼리 구성]")
    for t in record.plan.targets:
        where = f"{t.node_name} ({t.node_id}, {t.method})" if t.linked else "그래프에서 못 찾음"
        attrs = f"  사용자 지정: {t.mention.attributes}" if t.mention.attributes else ""
        print(f"  '{t.mention.text}' -> {where}{attrs}")
    if not record.plan.targets:
        print("  대상 후보 없음")
    print(f"  속성 쿼리 {len(record.plan.queries)}개")
    print("\n[02 검색]")
    for r in record.retrieval.results:
        print(f"  {r.target_id}.{r.aspect}: {r.status} ({len(r.facts)}건)")
    if not record.retrieval.results:
        print("  실행할 쿼리 없음")
    print("\n[03 프롬프트]")
    print(f"  positive: {record.prompt.positive}")
    print(f"  negative: {record.prompt.negative}")
    print("\n[04 이미지]")
    for p in record.image_paths:
        print(f"  {p}")


def _print_plugins() -> None:
    for category, registry in REGISTRIES.items():
        print(f"{category}: {', '.join(registry.names()) or '(없음)'}")
        for module, error in registry.import_errors.items():
            print(f"  ! 불러오지 못함 {module}: {error}")


def _use_utf8_console() -> None:
    """Windows 콘솔에서 한글이 깨지지 않도록."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
