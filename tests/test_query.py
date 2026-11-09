from __future__ import annotations

from pathlib import Path

from conftest import FROG_GRAPH

from pipeline.config import load_config
from pipeline.plugins.embedder.hashing import HashingEmbedder
from pipeline.plugins.graph_store.json_store import JsonGraphStore
from pipeline.plugins.request_parser.kiwi import KiwiRequestParser
from pipeline.plugins.request_parser.simple import SimpleRequestParser
from pipeline.query.lexicon import Lexicon
from pipeline.query.linker import HybridLinker, LinkerSettings
from pipeline.schemas import Mention


def _linker(tmp_path: Path) -> HybridLinker:
    settings = LinkerSettings(cache_dir=str(tmp_path / "index"))
    return HybridLinker(JsonGraphStore(str(FROG_GRAPH)), HashingEmbedder(), settings)


def _mention(text: str) -> Mention:
    return Mention(text=text, start=0, end=len(text))


def test_linker_exact_hybrid_and_unmatched(tmp_path: Path):
    alias, typo, unrelated = _linker(tmp_path).link(
        [_mention("Tree Frog"), _mention("개구니"), _mention("자동차")]
    )
    assert (alias.node_id, alias.method) == ("tree_frog", "exact")  # 별칭, 대소문자/공백 무시
    assert (typo.node_id, typo.method) == ("frog", "hybrid")  # 글자 겹침으로 채택
    assert typo.candidates and typo.candidates[0]["node_id"] == "frog"
    assert not unrelated.linked


def test_node_vectors_are_cached(tmp_path: Path):
    _linker(tmp_path).link([_mention("개구니")])
    assert len(list((tmp_path / "index").glob("nodes-*.npy"))) == 1


def test_simple_parser_fallback():
    parser = SimpleRequestParser(Lexicon(load_config().lexicon))
    parsed = parser.parse("빨간 개구리를 그려줘")
    assert [(m.text, m.attributes) for m in parsed.mentions] == [("개구리", {"color": ["빨강"]})]


def test_spaced_latin_words_become_one_mention():
    lexicon = Lexicon(load_config().lexicon)
    for parser in (KiwiRequestParser(lexicon), SimpleRequestParser(lexicon)):
        parsed = parser.parse("Engro Holdings Limited 프로필 카드")
        assert [m.text for m in parsed.mentions] == ["Engro Holdings Limited"], parser.plugin_name


def test_latin_words_around_attribute_are_not_merged():
    lexicon = Lexicon({"attributes": {"color": {"빨강": ["red"]}}})
    parsed = KiwiRequestParser(lexicon).parse("Tree red Frog")
    assert [m.text for m in parsed.mentions] == ["Tree", "Frog"]
    assert parsed.mentions[1].attributes == {"color": ["빨강"]}
