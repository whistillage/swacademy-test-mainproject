"""경로 기준점. 설정 파일에 적힌 상대 경로는 모두 프로젝트 루트 기준으로 해석한다."""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def resolve(path: str | Path) -> Path:
    p = Path(path)
    return p if p.is_absolute() else PROJECT_ROOT / p
