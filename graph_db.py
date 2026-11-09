"""그래프 DB 관리 CLI.

  python graph_db.py init [--force]   빈 그래프 DB 생성 (현재 json 저장소만 지원)
  python graph_db.py stats            노드/관계 수, 종류별 개수 (형식 검사 포함)
"""

from __future__ import annotations

import argparse
import json
import sys

from pipeline.config import ConfigError, load_config
from pipeline.plugins import GRAPH_STORES
from pipeline.plugins.graph_store.base import GraphDataError
from pipeline.plugins.graph_store.json_store import JsonGraphStore
from pipeline.registry import PluginError


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="그래프 DB 관리")
    parser.add_argument("--config", help="설정 파일 경로 (기본: config/config.yaml)")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="빈 그래프 DB 생성")
    init.add_argument("--force", action="store_true", help="이미 있으면 덮어쓰기")
    sub.add_parser("stats", help="그래프 요약 정보")
    args = parser.parse_args(argv)

    try:
        spec = load_config(args.config).plugins["graph_store"]
        if args.command == "init":
            if spec.name != "json":
                print(f"init 은 json 저장소에서만 지원합니다. 현재 graph_store: {spec.name}", file=sys.stderr)
                return 1
            path = JsonGraphStore.create_empty(spec.params["path"], overwrite=args.force)
            print(f"빈 그래프 DB 를 만들었습니다: {path}")
        else:
            store = GRAPH_STORES.create(spec)
            try:
                print(json.dumps(store.stats(), ensure_ascii=False, indent=2))
            finally:
                store.close()
    except (ConfigError, PluginError, GraphDataError, FileNotFoundError, FileExistsError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
