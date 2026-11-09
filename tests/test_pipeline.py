from __future__ import annotations

import json
from pathlib import Path

from pipeline.config import load_config
from pipeline.plugins.graph_store.json_store import JsonGraphStore
from pipeline.runner import Pipeline

EXPECTED_FILES = {
    "00_request.txt",
    "01_query_plan.json",
    "02_retrieval.json",
    "03_prompt.json",
    "04_generation.json",
    "04_image.png",
    "run.json",
}


def _run(config, request: str):
    pipeline = Pipeline(config)
    try:
        return pipeline.run(request)
    finally:
        pipeline.close()


def _result(record, target_id: str, aspect: str):
    return next(r for r in record.retrieval.results if r.target_id == target_id and r.aspect == aspect)


def test_user_color_replaces_graph_query(make_config):
    record = _run(make_config(), "빨간 개구리를 그려줘")

    [target] = record.plan.targets
    assert (target.node_id, target.method) == ("frog", "exact")
    assert target.mention.attributes == {"color": ["빨강"]}
    # 사용자가 색을 정했으므로 색상 쿼리는 만들지 않는다
    assert [q.aspect for q in record.plan.queries] == ["body_part", "texture", "habitat"]

    body = _result(record, "frog", "body_part")
    assert body.status == "found"
    assert ["뒷다리", "길다"] in [f.names for f in body.facts]
    assert ["물갈퀴"] in [f.names for f in body.facts]  # 더 갈 곳이 없는 경로도 결과에 포함

    positive = record.prompt.positive
    assert positive.startswith("개구리(빨강 색, ")
    assert "뒷다리(길다)" in positive and "배경 연못" in positive
    assert "초록" not in positive  # 그래프의 색보다 사용자 지정이 우선

    assert {p.name for p in record.run_dir.iterdir()} == EXPECTED_FILES
    run_info = json.loads((record.run_dir / "run.json").read_text(encoding="utf-8"))
    assert "error" not in run_info


def test_missing_aspect_is_inherited_from_parent(make_config):
    record = _run(make_config(), "청개구리 그려줘")

    assert record.plan.targets[0].node_id == "tree_frog"
    color = _result(record, "tree_frog", "color")
    assert (color.status, color.facts[0].names) == ("found", ["연두"])
    texture = _result(record, "tree_frog", "texture")
    assert (texture.status, texture.source_id) == ("inherited", "frog")
    assert "매끈하고 축축함 질감" in record.prompt.positive


def test_attributes_attach_to_nearest_following_target(make_config):
    record = _run(make_config(), "빨간 개구리와 파란 연잎을 그려줘")

    targets = {t.node_id: t.mention.attributes for t in record.plan.targets}
    assert targets == {"frog": {"color": ["빨강"]}, "lily_pad": {"color": ["파랑"]}}
    # 연잎(Plant)은 _default 체크리스트를 쓰고, 색은 사용자 지정이라 shape 만 질의
    assert [q.aspect for q in record.plan.queries if q.target_id == "lily_pad"] == ["shape"]
    assert "연잎(파랑 색)" in record.prompt.positive


def test_empty_graph_runs_end_to_end_without_model_download(make_config, tmp_path: Path):
    empty = JsonGraphStore.create_empty(tmp_path / "empty.json")
    # config.yaml 의 기본 임베딩(sentence_transformers). 그래프가 비어 있으면 모델을 로드하지 않아야 한다.
    config = make_config(graph_path=empty, embedder=load_config().plugins["embedder"])

    record = _run(config, "빨간 개구리를 그려줘")

    [target] = record.plan.targets
    assert not target.linked and target.mention.text == "개구리"
    assert record.plan.queries == []
    assert record.prompt.positive.startswith("개구리(빨강 색)")
    assert record.image_paths[0].read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_failed_step_still_writes_run_json(make_config):
    config = make_config()
    pipeline = Pipeline(config)

    def broken(_request):
        raise RuntimeError("모델 호출 실패")

    pipeline.generator.generate = broken  # type: ignore[method-assign]
    try:
        pipeline.run("개구리")
    except RuntimeError:
        pass
    else:
        raise AssertionError("예외가 전달되지 않음")

    [run_dir] = list(config.output_dir.iterdir())
    info = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert info["error"]["message"] == "모델 호출 실패"
    assert (run_dir / "03_prompt.json").exists()  # 실패 전 단계 결과는 남는다
