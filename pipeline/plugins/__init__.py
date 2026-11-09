"""교체 가능한 구성요소(플러그인) 모음.

카테고리          인터페이스                                   config.yaml 항목
graph_store       graph_store/base.py      GraphStore          graph_store
embedder          embedder/base.py         Embedder            embedder
request_parser    request_parser/base.py   RequestParser       request_parser
translator        translator/base.py       Translator          translator
image_generator   image_generator/base.py  ImageGenerator      image_generator

새 구현을 추가하려면 해당 폴더에 파일을 만들고 @register("이름") 을 붙인 뒤
config.yaml 의 name 을 바꾸면 된다. 파이프라인 코드는 수정하지 않는다.
"""

from __future__ import annotations

from .embedder.base import REGISTRY as EMBEDDERS
from .graph_store.base import REGISTRY as GRAPH_STORES
from .image_generator.base import REGISTRY as IMAGE_GENERATORS
from .request_parser.base import REGISTRY as REQUEST_PARSERS
from .translator.base import REGISTRY as TRANSLATORS

REGISTRIES = {
    "graph_store": GRAPH_STORES,
    "embedder": EMBEDDERS,
    "request_parser": REQUEST_PARSERS,
    "translator": TRANSLATORS,
    "image_generator": IMAGE_GENERATORS,
}
