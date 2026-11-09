"""RDF 저장소 + SPARQL 검색 + 값 규칙 + 카드 합성 (회사 프로필 카드)."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from pipeline.plugins.graph_store.rdf_store import RdfGraphStore
from pipeline.prompt.values import ValueFormatter
from pipeline.render.card import CardRenderer, CardStyle
from pipeline.runner import Pipeline
from pipeline.schemas import Fact

MINI_MARKET = Path(__file__).parent / "fixtures" / "mini_market.ttl"


def _run(config, request: str):
    pipeline = Pipeline(config)
    try:
        return pipeline.run(request)
    finally:
        pipeline.close()


def _result(record, aspect: str):
    return next(r for r in record.retrieval.results if r.aspect == aspect)


# ---------------------------------------------------------------- RDF 저장소


def test_rdf_store_indexes_only_configured_classes():
    store = RdfGraphStore(
        [str(MINI_MARKET)],
        index_classes=[":Company"],
        name_predicates=[":hasCompanyName"],
        alias_predicates=[":hasCompanyIdentifier", "skos:altLabel"],
    )
    nodes = {n.id: n for n in store.iter_nodes()}

    assert set(nodes) == {"t:acme", "t:bolt"}
    acme = nodes["t:acme"]
    assert (acme.label, acme.name) == ("Company", "Acme Mining Limited")
    assert set(acme.aliases) == {"ACME", "애크미"}
    assert acme.properties["hasCompanyIdentifier"] == "ACME"
    assert [e.type for e in store.out_edges("t:acme")] == ["isClassifiedByIndustrySector"]


def test_rdf_store_sparql_binds_target():
    store = RdfGraphStore([str(MINI_MARKET)])
    rows = store.query(
        'SELECT ?value WHERE { ?o :isObservationOf ?target ; :hasMetricName "EPS" ; :hasMetricValue ?value }'
        " ORDER BY ?value",
        {"target": "t:acme"},
    )
    assert [r["value"] for r in rows] == [10.0, 12.5]


# ---------------------------------------------------------------- 값 규칙


def test_value_rules_number_clamp_lookup_when():
    rules = {
        "growth": {
            "number": {"decimals": 1, "sign": True, "suffix": "%", "clamp": 999},
            "when": [{"if": ">= 0", "set": {"arrow": "▲"}}, {"if": "< 0", "set": {"arrow": "▼"}}],
        },
        "sector": {"lookup": {"Mining": {"ko": "광업"}}, "default": {"ko": "{raw}"}},
    }
    fmt = ValueFormatter(rules)

    def field(aspect, value):
        return fmt.field(aspect, [Fact(names=[str(value)], kind="sparql", values={"value": value})])

    assert (field("growth", 25.04)["text"], field("growth", 25.04)["arrow"]) == ("+25.0%", "▲")
    assert (field("growth", -1234.5)["text"], field("growth", -1234.5)["arrow"]) == ("-999%↓", "▼")
    assert field("sector", "Mining")["ko"] == "광업"
    assert field("sector", "Unknown")["ko"] == "Unknown"
    assert fmt.field("growth", [])["text"] == ""  # 값이 없으면 빈 필드


# ---------------------------------------------------------------- 전체 파이프라인


def test_company_card_end_to_end(make_company_config):
    record = _run(make_company_config(), "ACME 카드 만들어줘")

    [target] = record.plan.targets  # '카드' 는 무시 단어
    assert (target.node_id, target.method) == ("t:acme", "exact")
    assert all(q.sparql or q.properties for q in record.plan.queries)

    # 값이 여러 개면 SPARQL 에서 최신 값 하나만 고른다
    eps = _result(record, "eps")
    assert [f.values["value"] for f in eps.facts] == [12.5]
    assert _result(record, "close").facts[0].values["value"] == 1234.567

    card = record.prompt.card
    assert card["title"] == "Acme Mining Limited"
    assert card["subtitle"] == "ACME · Mining Sector Classifier"  # 대응표에 없는 업종은 원문
    values = {row["label"]: row["value"] for row in card["rows"]}
    assert values["주당순이익 (EPS)"] == "TST 12.50"
    assert values["전년 대비 이익"] == "▲ +25.0%"
    assert values["종가"] == "TST 1,234.57"
    assert "반기 실적 발표 (2026-02-20)" in card["footer"]
    assert "Test Stock Exchange" in card["footer"]

    # 배경 프롬프트에는 숫자가 아니라 분위기만 들어간다
    assert "Warm golden morning light" in record.prompt.positive
    assert "12.5" not in record.prompt.positive

    names = {p.name for p in record.run_dir.iterdir()}
    assert {"04_background.png", "04_image.png"} <= names
    generation = json.loads((record.run_dir / "04_generation.json").read_text(encoding="utf-8"))
    assert generation["card_overlay"] is True


def test_missing_values_show_placeholder(make_company_config):
    record = _run(make_company_config(), "BOLT 카드")

    card = record.prompt.card
    assert card["subtitle"] == "BOLT · 비료"
    values = {row["label"]: row for row in card["rows"]}
    assert values["전년 대비 이익"]["value"] == "▼ -999%↓"
    assert values["전년 대비 이익"]["color"] == "#F87171"
    assert values["종가"]["value"] == "TST –"  # 종가 관측치가 없음
    assert "최근 공시: – (–)" in card["footer"]
    assert "Overcast" in record.prompt.positive


def test_korean_alias_links_company(make_company_config):
    record = _run(make_company_config(), "애크미 인포그래픽")
    assert record.plan.targets[0].node_id == "t:acme"


def test_unknown_company_gives_no_card(make_company_config):
    record = _run(make_company_config(), "ZETA 카드")
    assert not record.plan.targets[0].linked
    assert record.prompt.card == {}
    assert "04_background.png" not in {p.name for p in record.run_dir.iterdir()}


def test_card_renderer_keeps_size_and_draws_panel():
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (512, 512), "#FFFFFF").save(buffer, format="PNG")
    card = {"title": "Acme", "subtitle": "ACME · 광업", "rows": [{"label": "EPS", "value": "TST 1.00"}],
            "footer": "출처"}
    out = Image.open(io.BytesIO(CardRenderer(CardStyle()).render(buffer.getvalue(), card)))

    assert out.size == (512, 512)
    assert out.getpixel((5, 500))[0] < 100  # 왼쪽은 어두운 패널
    assert out.getpixel((506, 5)) == (255, 255, 255)  # 오른쪽은 원본 그대로


def test_sparql_on_json_store_fails_clearly(make_config):
    config = make_config()
    config.aspects["labels"]["Animal"]["color"] = {"sparql": "SELECT ?value WHERE { ?target ?p ?value }"}
    with pytest.raises(NotImplementedError, match="SPARQL"):
        _run(config, "개구리")


def test_full_company_name_with_spaces_is_one_target(make_company_config):
    record = _run(make_company_config(), "Acme Mining Limited 프로필 카드")
    [target] = record.plan.targets  # 'Limited' 가 따로 떨어져 다른 회사에 연결되지 않는다
    assert (target.mention.text, target.node_id, target.method) == ("Acme Mining Limited", "t:acme", "exact")
