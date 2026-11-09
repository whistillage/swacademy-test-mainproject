# GraphRAG 기반 이미지 생성 파이프라인

그래프 DB에서 대상의 정보를 찾아 이미지 생성 프롬프트를 만들고, 그 프롬프트로 이미지를 생성한다.
에이전트 없이 순차 워크플로우로 동작하며, **LLM을 호출하지 않는다.**

현재 설정은 **회사 프로필 카드**다. [OntoKG-EQ](data/graph/psx/SOURCE.md) 지식 그래프(파키스탄 증권거래소 4개 회사)에서
SPARQL로 업종, EPS, 이익 성장률, 종가, 최근 공시를 찾는다. 이미지 모델(FLUX.2-klein-4B)이 업종 배경을 그리고,
숫자와 한글은 Pillow로 그 위에 찍는다.

```
요청 → [01 쿼리 구성] → [02 GraphRAG 검색] → [03 프롬프트 구성] → [04 이미지 생성 + 카드 글자 합성]
```

| 단계 | 하는 일 | 방식 |
|---|---|---|
| 01 쿼리 구성 | 요청 분석 → 대상 노드 찾기 → 속성별 쿼리 생성 | 형태소 분석 + 하이브리드 검색(벡터+키워드, RRF) + 속성 체크리스트 |
| 02 검색 | 속성별 SPARQL 실행 (또는 관계를 따라가며 값 수집) | SPARQL / 그래프 순회 |
| 03 프롬프트 구성 | 배경 프롬프트 + 카드 내용 만들기 | 템플릿 + 대응표·규칙 |
| 04 이미지 생성 | 배경 생성 → 카드 글자 합성 | diffusers 플러그인 + Pillow |

## 실행 (Ubuntu / WSL)

Python 3.12(Ubuntu 24.04, WSL2)와 3.13(Windows)에서 확인했다.

```bash
# 처음 한 번
sudo apt install python3-venv       # venv 모듈이 없을 때만
python3 -m venv .venv
source .venv/bin/activate           # Windows: .venv\Scripts\activate
pip install -r requirements.txt
# 이미지 모델을 쓰려면 아래 "GPU 설치"도 진행

# 실행
python graph_db.py stats            # 그래프 요약 (트리플 수, 노드 종류)
python run.py "OGDC 카드 만들어줘"
python run.py "엥그로 카드" --image-generator dummy   # GPU 없이 확인 (자리표시 배경)
python run.py --list-plugins        # 등록된 플러그인 확인
python -m pytest                    # 테스트 (GPU 모델을 불러오지 않음)
```

찾을 수 있는 회사와 요청에 쓸 수 있는 이름 (정확히 일치하면 바로 찾고, 아니면 임베딩 검색으로 찾는다)

| 회사 | 종목코드 | 한국어 별칭 | 업종 |
|---|---|---|---|
| Oil and Gas Development Company Limited | `OGDC` | 오지디씨, 파키스탄석유가스개발 | 석유·가스 탐사 |
| Pakistan Petroleum Limited | `PPL` | 파키스탄석유 | 석유·가스 탐사 |
| Fauji Fertilizer Company Limited | `FFC` | 파우지비료, 파우지 | 비료 |
| Engro Holdings Limited | `ENGROH` | 엥그로, 엥그로홀딩스 | 비료 |

한국어 별칭은 [aliases_ko.ttl](data/graph/psx/aliases_ko.ttl)에서 추가한다. 요청 예시:
`OGDC 카드 만들어줘`, `파우지비료 인포그래픽 보여줘`, `Engro Holdings Limited 프로필 카드`

### GPU 설치 (이미지 생성 모델용)

```bash
# CUDA 용 torch (RTX 50 시리즈는 CUDA 12.8 이상 빌드 필요). 드라이버의 CUDA 버전은 nvidia-smi 로 확인
pip install torch==2.15.0 --index-url https://download.pytorch.org/whl/cu132 --force-reinstall --no-deps
pip install -r requirements-gpu.txt
```

FLUX.2-klein-4B 가중치는 약 16GB이고 첫 실행 때 내려받는다(`~/.cache/huggingface`).
8GB GPU에서는 `quantization: nf4`(4비트, 약 5GB)로 불러온다. GPU 메모리가 충분하면 `null`로 끈다.

RTX 5060(8GB) 실측: 한 장에 약 25초(모델 로드 포함, 1024×1024, 4스텝), GPU 최대 사용량 약 7.2GB, 카드 글자 합성 0.2초.
`python run.py` 한 번이 한 장이므로 매번 모델을 다시 불러온다.

### 실행 결과

`output/<실행시각>/`에 단계별로 저장된다.

| 파일 | 내용 |
|---|---|
| `00_request.txt` | 요청 원문 |
| `01_query_plan.json` | 분석 결과, 찾은 대상 노드(후보와 점수 포함), 속성별 쿼리, 생략한 항목과 이유 |
| `02_retrieval.json` | 속성별 검색 결과 (found / inherited / missing). SPARQL 결과 행 전체(날짜, 출처 URL 포함) |
| `03_prompt.json` | 배경 프롬프트, 카드 내용(`card`), 각 값이 어디서 왔는지(`slots`) |
| `04_background.png` | 이미지 모델이 그린 배경 (카드가 있을 때) |
| `04_image.png`, `04_generation.json` | 최종 이미지, 모델 요청/응답 정보 (seed, GPU 메모리, 무시한 옵션) |
| `run.json` | 사용한 플러그인, 단계별 소요 시간, 오류 (중간에 실패해도 남음) |

## 설정 파일

| 파일 | 내용 |
|---|---|
| `config/config.yaml` | 플러그인 선택 (그래프 DB, 이미지 모델 등), 이미지 크기, 카드 합성 스타일(`overlay`) |
| `config/aspects.yaml` | 노드 종류별로 찾을 속성과 그 SPARQL 쿼리 |
| `config/templates.yaml` | 배경 프롬프트, 값 규칙(대응표, 숫자 형식, 조건), 카드 구성 |
| `config/lexicon.yaml` | 사용자 지정 속성 사전, 대상에서 뺄 단어(카드, 인포그래픽 ...) |

### 카드 항목 추가 예시 (배당금)

1. `aspects.yaml`의 `Company` 아래에 속성과 SPARQL 추가
   ```yaml
   dividend:
     sparql: |
       SELECT ?value ?date WHERE {
         ?obs :isObservationOf ?target ; :hasMetricName "dividend" ;
              :hasMetricValue ?value ; :hasObservationDate ?date .
       } ORDER BY DESC(?date) LIMIT 1
   ```
2. `templates.yaml`의 `values`에 표시 형식, `card.rows`에 행 추가
   ```yaml
   values:
     dividend: {number: {decimals: 2}}
   card:
     rows:
       - {label: "배당금", value: "{currency[text]} {dividend[text]}", note: "{dividend[date]}"}
   ```

템플릿 빈칸은 `{속성[필드]}`다. 필드는 `text`(표시용), `raw`(원래 값), SPARQL 변수(`date` 등),
값 규칙이 만든 필드(`ko`, `scene`, `arrow`, `color`, `mood`)다. 값이 없으면 카드에는 `–`가 찍힌다.

## 미정 사항 교체 방법

교체 가능한 구성요소는 모두 플러그인이다. **`config/config.yaml`의 `name`(과 `params`)만 바꾸면** 교체되고 파이프라인 코드는 손대지 않는다.

| 미정 사항 | 바꿀 곳 |
|---|---|
| 이미지 생성 모델 (diffusers 모델) | `image_generator.params.model_id` |
| 이미지 생성 모델 (API 등 다른 방식) | `pipeline/plugins/image_generator/`에 플러그인 추가 → `image_generator.name` |
| 그래프 데이터 (다른 RDF 파일) | `graph_store.params.paths` |
| 그래프 DB (다른 종류) | `pipeline/plugins/graph_store/`에 `GraphStore` 구현 추가 → `graph_store.name` |
| 찾을 정보 | `config/aspects.yaml` |
| 프롬프트 문구, 카드 구성, 한글 대응표 | `config/templates.yaml` |
| 영어 변환 여부 | `pipeline/plugins/translator/`에 번역 플러그인 추가 → `translator.name` |
| 임베딩 모델 | `embedder.params.model_name` (예: `BAAI/bge-m3`) |

### 이미지 생성 모델 바꾸기

diffusers로 불러올 수 있는 HuggingFace 모델이면 `model_id`만 바꾸면 된다. 모델이 지원하지 않는 옵션(예: FLUX의 `negative_prompt`)은
자동으로 빼고 `04_generation.json`의 `ignored`에 기록한다.

```yaml
image_generator:
  name: diffusers
  params:
    model_id: stabilityai/sdxl-turbo
    quantization: null
    num_inference_steps: 4
    guidance_scale: 0.0
```

API 방식 등 다른 종류의 모델은 `pipeline/plugins/image_generator/_template.py`를 복사해 플러그인을 만든다.
카드 글자 합성은 모델과 별도로 동작하므로 모델을 바꿔도 그대로다.

### 그래프 DB 붙이기

`GraphStore`(`pipeline/plugins/graph_store/base.py`)의 메서드 4개를 구현한다:
`iter_nodes()`, `get_node()`, `out_edges()`, `stats()`. SPARQL 쿼리를 쓰려면 `query()`도 구현한다.
노드는 `id / label(종류) / name / aliases / description / properties`, 관계는 `source / target / type`으로 변환해 돌려준다.

## 폴더 구조

```
config/              config.yaml, aspects.yaml, templates.yaml, lexicon.yaml
data/graph/psx/      OntoKG-EQ PSX 그래프(원본) + 한국어 별칭 + 출처
data/index/          노드 임베딩 캐시 (자동 생성)
pipeline/
  registry.py        플러그인 등록/로드
  runner.py          단계 조립과 순차 실행, 결과 저장
  schemas.py         단계 간 데이터 형식
  query/             01: lexicon(속성 사전), linker(대상 노드 찾기), planner(속성별 쿼리), builder
  retrieval/         02: executor(SPARQL / 경로 탐색 + 상속)
  prompt/            03: builder(템플릿 조합), values(대응표, 숫자 형식, 조건 규칙)
  render/            04: card(Pillow 카드 글자 합성)
  plugins/           graph_store(rdf, json), embedder, request_parser, translator, image_generator(diffusers, dummy)
tests/               fixtures/mini_market.ttl(회사 카드 테스트), frog_*(경로 탐색 방식 예시)
run.py               파이프라인 CLI
graph_db.py          그래프 DB 관리 CLI
```

## 알아둘 점

- 카드는 요청에서 처음 찾은 회사 하나로 만든다.
- 띄어 쓴 영문 단어는 하나의 대상으로 합친다 (`Engro Holdings Limited` → 한 회사). 그래서 `OGDC PPL`처럼
  영문 종목코드 두 개를 띄어 쓰면 하나로 합쳐져 정확히 일치하지 않는다. 사이에 색상 같은 속성 표현이 있으면 합치지 않는다.
- 통화(`currency`)는 그래프 안의 환율 관측치에서 가져온다. 그래프에 시장이 하나일 때만 맞으므로, 여러 시장을 합치면 쿼리를 고쳐야 한다.
- 경로 탐색 방식(JSON 그래프, `path`, 상위 개념 상속)도 그대로 쓸 수 있다. 예시는 `tests/fixtures/frog_*`.
- 대상 노드 찾기의 채택 기준값(`linker.min_vector_score`, `min_keyword_overlap`)은 임베딩 모델과 실제 데이터로 다시 맞춰야 한다.
- 임베딩 모델(약 470MB)은 이름이나 별칭이 정확히 일치하지 않는 표현을 처음 검색할 때 다운로드된다.
