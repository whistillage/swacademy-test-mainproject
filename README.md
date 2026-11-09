# GraphRAG 기반 이미지 생성 파이프라인

그래프 DB에서 대상의 특성을 찾아 이미지 생성 프롬프트를 만들고, 그 프롬프트로 이미지를 생성한다.
에이전트 없이 순차 워크플로우로 동작하며, **LLM을 호출하지 않는다.**

```
요청 → [01 쿼리 구성] → [02 GraphRAG 검색] → [03 프롬프트 구성] → [04 이미지 생성]
```

| 단계 | 하는 일 | 방식 |
|---|---|---|
| 01 쿼리 구성 | 요청 분석 → 대상 노드 찾기 → 속성별 쿼리 생성 | 형태소 분석 + 하이브리드 검색(벡터+키워드, RRF) + 속성 체크리스트 |
| 02 검색 | 속성별로 관계를 따라가며 값 수집, 없으면 상위 개념에서 상속 | 그래프 순회 |
| 03 프롬프트 구성 | 빈칸 채우기 (사용자 지정 속성 우선) | 템플릿 조합 |
| 04 이미지 생성 | 프롬프트 → 이미지 | 플러그인 (현재 dummy) |

## 실행

```bash
# 가상환경 (Python 3.13)
.venv\Scripts\activate
pip install -r requirements.txt     # 새로 설치할 때만

python graph_db.py init             # 빈 그래프 DB 생성 (data/graph/graph.json, 이미 생성됨)
python graph_db.py stats            # 그래프 요약 + 형식 검사
python run.py "빨간 개구리를 그려줘"
python run.py --list-plugins        # 등록된 플러그인 확인
python -m pytest                    # 테스트
```

실행 결과는 `output/<실행시각>/`에 단계별로 저장된다.

| 파일 | 내용 |
|---|---|
| `00_request.txt` | 요청 원문 |
| `01_query_plan.json` | 분석 결과, 찾은 대상 노드(후보와 점수 포함), 속성별 쿼리, 생략한 항목과 이유 |
| `02_retrieval.json` | 속성별 검색 결과 (found / inherited / missing) |
| `03_prompt.json` | 최종 프롬프트, 각 값이 어디서 왔는지 |
| `04_image.png`, `04_generation.json` | 생성 이미지, 모델 요청/응답 정보 |
| `run.json` | 사용한 플러그인, 단계별 소요 시간, 오류 (중간에 실패해도 남음) |

## 미정 사항 교체 방법

교체 가능한 구성요소는 모두 플러그인이다. **`config/config.yaml`의 `name`(과 `params`)만 바꾸면** 교체되고 파이프라인 코드는 손대지 않는다.

| 미정 사항 | 바꿀 곳 |
|---|---|
| 이미지 생성 모델 | `pipeline/plugins/image_generator/`에 플러그인 추가 → `image_generator.name` |
| 그래프 DB | `pipeline/plugins/graph_store/`에 `GraphStore` 구현 추가 → `graph_store.name` |
| 그래프 스키마 (노드 종류, 관계 이름) | `config/aspects.yaml` |
| 어떤 이미지를 만들지 (프롬프트 문구, 스타일) | `config/templates.yaml` |
| 영어 변환 여부 | `pipeline/plugins/translator/`에 번역 플러그인 추가 → `translator.name` |
| 임베딩 모델 | `embedder.params.model_name` (예: `BAAI/bge-m3`) |
| 사용자 지정 속성 감지 범위 | `config/lexicon.yaml` |

### 이미지 생성 모델 붙이기

1. `pipeline/plugins/image_generator/_template.py`를 복사해 새 파일로 저장 (예: `my_model.py`)
2. `@register("my_model")`을 붙이고 `generate(ImageRequest) -> GenerationResult`를 구현
3. `config.yaml`을 수정
   ```yaml
   image_generator:
     name: my_model
     params:
       api_key: ${IMAGE_API_KEY}   # 실제 값은 .env 에 저장
   ```
4. `python run.py --list-plugins`로 등록됐는지 확인

프로젝트 밖의 클래스도 `name: 모듈경로:클래스명` 형식으로 등록 없이 바로 쓸 수 있다.
한 번만 다른 모델로 돌려보려면 `python run.py "..." --image-generator 이름`을 쓴다.

### 그래프 DB 붙이기

`GraphStore`(`pipeline/plugins/graph_store/base.py`)의 메서드 4개만 구현하면 된다:
`iter_nodes()`, `get_node()`, `out_edges()`, `stats()`.
노드는 `id / label(종류) / name / aliases / description / properties`, 관계는 `source / target / type`으로 변환해 돌려준다.

## 폴더 구조

```
config/              config.yaml(플러그인 선택), aspects.yaml, templates.yaml, lexicon.yaml
data/graph/          그래프 DB (현재 빈 JSON)
data/index/          노드 임베딩 캐시 (자동 생성)
pipeline/
  registry.py        플러그인 등록/로드
  runner.py          단계 조립과 순차 실행, 결과 저장
  schemas.py         단계 간 데이터 형식
  query/             01: lexicon(속성 사전), linker(대상 노드 찾기), planner(속성별 쿼리), builder
  retrieval/         02: executor(쿼리 실행 + 상속)
  prompt/            03: builder(템플릿 조합)
  plugins/           graph_store, embedder, request_parser, translator, image_generator
tests/               fixtures/frog_graph.json(테스트 전용 예시 그래프)
run.py               파이프라인 CLI
graph_db.py          그래프 DB 관리 CLI
```

## 알아둘 점

- `config/aspects.yaml`의 `Animal` 항목과 테스트용 개구리 그래프는 **형식 예시**다. 실제 그래프 스키마가 정해지면 교체한다.
- 대상 노드 찾기의 채택 기준값(`linker.min_vector_score`, `min_keyword_overlap`)은 임베딩 모델과 실제 데이터로 다시 맞춰야 한다.
- 임베딩 모델(약 470MB)은 그래프에 노드가 있고, 이름이 정확히 일치하지 않는 표현을 처음 검색할 때 다운로드된다.
- 요청 속 속성(예: "빨간")은 바로 뒤에 오는 대상에 붙는다. 1차 버전은 색상만 감지한다.
