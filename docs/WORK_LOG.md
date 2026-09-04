# Work Log

## 2026-08-24 (2) — 실시간 배경 이미지 분석 폴백 (claude)

- 시작: 시간 미기록
- 완료: 2026-08-24 KST
- 작업 agent: claude (Sonnet 5)

### 작업 내용

사용자 요청으로 백엔드(`MiriGangNeung_BackEnd`) 원격 저장소를 `gh repo clone`으로
다시 조사해 "현재 사진 호출 체계와 알고리즘"을 확인하고, 그 결과를 Agentic AI의
프롬프트 생성 단계(이미지 분석 리포트 생성)에 반영했다.

조사 결과 아래 3번째 항목 "장소 특징 VLM 사전 분석 파이프라인"(같은 날짜, ADR-0003)
이 세운 전제 하나가 실제와 다르다는 것을 발견했다.

- 백엔드에는 배경 후보를 제공하는 경로가 셋이다: (1) `GET /api/v1/places/{id}` →
  `images[]`(ADR-0003이 분석 대상으로 삼은 경로, `Place.id` UUID에 종속), (2)
  `GET /api/v1/award-photos`(공모전 수상작, `AwardPhotoService`), (3)
  `GET /api/v1/tourism-photos`(관광사진갤러리, `TourismPhotoService`, **DTO에
  `copyrightCode` 필드 자체가 없음**).
- 백엔드 설계 문서(`docs/superpowers/specs/2026-08-10-tour-photo-source-tabs-design.md`)
  에 따르면 사용자가 실제로 배경을 고르는 화면은 (1)이 아니라 (2)/(3) 두 탭이고,
  기본 탭은 `award`다. 같은 문서가 명시: 두 소스의 사진 ID는 "표시용 식별자"일
  뿐 `Place.id`가 아니다.
- 즉 사용자가 실제로 고르는 배경 상당수는 `onePickPlaceId`가 `Place` UUID가
  아니어서, ADR-0003의 `place_insights.json`(Place UUID 키 오프라인 캐시)에
  애초에 매칭될 수 없다.

이를 보완하기 위해 ADR-0004를 작성하고, "오프라인 캐시가 미스일 때만 이번 요청의
실제 배경 이미지 바이트를 실시간 분석해 프롬프트 힌트로 쓰는" 폴백 단계를
추가했다. 배경 바이트는 소스가 무엇이든 매 요청 `background` 필드로 이미
전달되므로, ID 매칭에 의존하지 않는 이 방법이 세 소스 모두에 동작한다.

- `app/providers/base.py`: `BackgroundAnalysis` dataclass, `analyze_background()`
  추상 메서드 추가 (모든 `ImageCompositionProvider` 구현체·테스트 더블에 반영).
- `prompts/background_analysis_v1.md`(신규): `scripts/analyze_top_places.py`의
  오프라인 분석과 필드명을 맞춘 JSON 응답 스키마.
- `app/providers/gemini.py::analyze_background()`: 기존 `_ask_json()`(스타일분석·
  품질검사가 쓰는 JSON-fence 파싱 경로) 재사용 — 새 비용 등급 없음.
- `app/providers/mock.py::analyze_background()`: 고정값 스텁.
- `app/places/backgrounds.py`: `has_precomputed_place_context()`(신규, 1·2순위
  캐시 히트 여부만 확인) + `resolve_place_context()`에 3순위(`background_analysis`)
  추가. 우선순위: 개발 카탈로그 → `place_insights.json` → **실시간 분석(신규)** →
  백엔드 텍스트 필드 → 범용 문구.
- `app/jobs/runner.py::_execute()`: `has_precomputed_place_context()`로 캐시
  미스를 확인한 뒤에만 `provider.analyze_background()`를 호출, 실패는 로그만
  남기고 다음 우선순위로 폴백 (Job 전체를 실패시키지 않음).
- `docs/adr/0004-realtime-background-analysis.md`(신규): 위 조사 결과와 설계
  결정, ADR-0003의 "요청마다 VLM 호출 기각" 대안과의 관계(뒤집는 게 아니라
  캐시 미스 폴백으로 보완) 기록.
- `docs/AI_API_CONTRACT.md`: `onePickPlaceId` 관련 각주에 백엔드 팀이 아직
  해소하지 않은 계약 공백 두 가지(award/gallery 탭의 비-UUID ID,
  tourism-photos의 `copyrightCode` 부재) 명시.
- 테스트: `tests/test_place_insights.py`에 `resolve_place_context()` 3순위
  단위 테스트 2건(라이브 분석 사용/빈 분석 무시) + `has_precomputed_place_context()`
  테스트 1건 추가. `tests/test_pipeline_units.py`의 `_StubProvider`/
  `_FlakyProvider`에 `analyze_background` 스텁 추가(추상 메서드 추가로 인한
  컴파일 대응).
  - `GeminiProvider`/`MockProvider`를 직접 mock하는 단위 테스트는 추가하지
    않았다 — 기존에도 이 두 클래스는 그런 방식으로 단위 테스트되지 않고
    (Gemini는 실제 키로 수동 스모크 테스트, Mock은 E2E로만 간접 검증) 있어,
    기존 테스트 전략과 다른 새 패턴을 끌어들이지 않는 쪽을 택했다.
- 검증: `.venv/bin/python -m pytest -q` 115 passed(기존 112 + 신규 3),
  `ruff check .`/`ruff format --check .` 클린.

## 2026-08-24 — 장소 특징 VLM 사전 분석 파이프라인 (claude)

- 시작: 시간 미기록
- 완료: 2026-08-24 KST
- 작업 agent: claude (Sonnet 5)

### 작업 내용

사용자 요청으로 백엔드의 "장소당 여러 사진" 기능을 다시 조사했다. 백엔드
`Place`/`PlaceImage`, `PlaceService`, `KoreanTourApiClient`, `PlaceController`를
재조사한 결과 두 가지를 확인했다.

1. 정확히 "5개"로 고정된 로직은 없다. 대신 `Place`는 이제 Tour API의
   `detailImage2` 갤러리 호출로 채워지는 개수 미확정(상한 없음)의 `PlaceImage`
   목록을 갖는다 (`GET /api/v1/places/{id}` → `images[]`). 이전 조사(ADR-0002)
   시점엔 `imageUrls`가 `List.of()`로 하드코딩돼 있었는데, 그 사이(2026-08-09
   커밋)에 실제 구현됐다.
2. 각 이미지에는 Tour API 원본 `cpyrhtDivCd` 필드가 `copyrightCode`로 내려온다.
   공식 매뉴얼(`api_manual_guide`)로 직접 확인한 결과 실제 값은 `Type1`(제1유형,
   출처표시만 하면 됨, 변경 허용)과 `Type3`(변경금지) 두 가지뿐이다. AI 합성은
   원본을 변형하는 행위이므로 `Type3` 이미지는 배경으로 쓸 수 없는데, 백엔드
   어디에도 이 필드로 걸러내는 로직이 없었다.

이를 바탕으로 "Type1 이미지가 많은 상위 10개 장소를 VLM으로 사전 분석해, 실제
합성 요청 때 그 리포트를 프롬프트에 쓴다"는 오프라인 배치 파이프라인을 설계·구현
했다 (ADR-0003). VLM은 이 개발 환경(RAM 7.5GB, GPU 없음 — 7B급 모델 로컬 구동
불가)의 제약을 감안해 Hugging Face 무료 Inference API로 원격 호출한다.

- `scripts/analyze_top_places.py`(신규): 백엔드 API에서 후보 선정 → Type1 필터 →
  상위 10개 장소 → 장소당 최대 5장 다운로드 → HF VLM 분석 → `place_insights.json`
  저장. 네트워크 I/O와 순수 로직(선정·필터·병합·JSON 파싱)을 분리해 테스트 가능하게
  했다.
- `app/places/insights.py`(신규): 런타임 로더. 파일이 없거나 비어 있어도 안전하게
  빈 결과를 돌려준다 — HF API에 런타임 의존성 없음.
- `app/places/backgrounds.py::resolve_place_context()`: 우선순위에 한 단계 추가
  (개발 카탈로그 → **insights 매칭(신규)** → 백엔드 제공 필드 → 범용 문구).
- `assets/places/place_insights.json`(신규, 커밋됨): 아직 `HF_TOKEN`이 없어 빈
  카탈로그 상태로 커밋. 배치를 실행하면 채워진다.
- `docs/AI_API_CONTRACT.md`: 배경 이미지는 `copyrightCode == "Type1"`인 것만
  forwarding해야 한다는 제약 추가.
- `requirements-dev.txt`에 `huggingface_hub` 추가 (배치 전용, 배포 이미지에는
  영향 없음).

이후 다른 로컬에서 먼저 원격(`origin/feat/initial-app-setup`)에 올라와 있던
2026-08-15~2026-08-22 작업(YuNet 얼굴 검출 모델, `variationMode` 재생성 옵션,
`estimatedCostUsd` 즉시 표시, Gemini 실키 스모크 테스트, 프롬프트 v2/v3)을 이
브랜치로 병합해 통합했다. 겹친 파일은 `.env.example`/`app/core/config.py`(두
기능의 설정 항목을 모두 유지)와 `docs/AI_API_CONTRACT.md`/`docs/PROJECT_STATUS.md`
(양쪽 변경 내용을 모두 반영)였다. `app/places/backgrounds.py`, `app/pipeline/
prompt.py` 등 실제 코드 경로는 서로 다른 파일을 건드려 충돌이 없었다.

### 주요 변경 파일

`scripts/analyze_top_places.py`, `app/places/insights.py`,
`app/places/backgrounds.py`, `app/core/config.py`, `assets/places/place_insights.json`,
`.env.example`, `requirements-dev.txt`, `docs/AI_API_CONTRACT.md`,
`docs/adr/0003-place-image-vlm-analysis.md`, `tests/test_place_insights.py`

### 테스트 결과

- 병합 전(이 브랜치 단독): `pytest -q` — 101 passed (기존 88개 + 이번 작업에서 추가 13개).
- 원격의 YuNet/variationMode 작업(2026-08-15~08-22, 아래 항목들)을 병합한 뒤:
  `pytest -q` — **112 passed** (101 + 원격 쪽에서 추가된 11개), `ruff check .` — All
  checks passed, `ruff format --check .` — 통과. 코드 충돌은 없었고(서로 다른 파일을
  건드림), `.env.example`/`app/core/config.py`/`docs/AI_API_CONTRACT.md`/
  `docs/PROJECT_STATUS.md`/`docs/WORK_LOG.md`는 문서·설정 텍스트가 겹쳐 수동으로 병합.

### 관련 commit

아직 커밋하지 않음.

### 다음 담당자에게

`HF_TOKEN` 발급 후 `python scripts/analyze_top_places.py --backend-base-url
<백엔드 URL>`을 1회 실행해 `place_insights.json`을 실제로 채워야 이 기능이
프롬프트에 반영된다. `docs/PROJECT_STATUS.md`의 "다음 작업 후보" 참고.

---

## 2026-08-22 (4) — PROVIDER_MAX_RETRIES 원복 (claude)

사용자 요청으로 테스트 중 비용 절감을 위해 낮췄던 `.env`의 `PROVIDER_MAX_RETRIES`를
`0` → `2`(코드 기본값과 동일)로 원복하고 서버 재기동해 반영. `docs/PROJECT_STATUS.md`의
관련 메모도 갱신.

## 2026-08-22 — 실제 사진으로 로컬 E2E 및 Gemini 실키 스모크 테스트 (claude)

- 시작: 10:57 KST
- 완료: 11:10 KST
- 작업 agent: claude (Sonnet 5)

### 작업 내용

사용자가 실제로 서비스를 테스트해보고 싶다고 하여, `run` 스킬 패턴(백그라운드 기동 →
헬스체크 → curl 스모크)을 따라 로컬 서버(`python main.py`)를 직접 띄우고 사용자가
제공한 얼굴 사진(`face-generator_gallery_1763099172_3441.avif`, AVIF→JPEG 변환)으로
실제 HTTP 요청을 넣었다.

1. **mock provider, `DONE` 전체 왕복 확인**: `POST /v1/generations` → 얼굴 검출(B3/B4)
   통과 → `QUEUED` → 폴링 1회 만에 `DONE`(`durationMs: 1715`). 결과 이미지를 다운로드해
   육안으로도 확인 (인물이 그라디언트 배경 위에 합성됨 — mock 로직대로 정상).
2. **Gemini 키 발급 후 실키 테스트**: 사용자가 Google AI Studio에서 키를 발급, `.env`에
   `AI_PROVIDER=gemini`/`GOOGLE_API_KEY` 설정. 같은 사진 + `background`(플레이스홀더
   그라디언트, `onePickPlaceId`가 개발 카탈로그에 없어 `BACKGROUND_REQUIRED`를 피하려고
   직접 첨부)로 재요청.
   - **버그 발견**: `GEMINI_VISION_MODEL` 기본값 `gemini-3.1-flash`가 이 키의 실제 모델
     목록(`GET /v1beta/models`)에 없어 매번 `404`. 스타일 분석이 조용히 빈 태그로
     폴백되어 겉으로는 실패가 안 보이는 상태였다. `gemini-3.1-flash-lite`로 교체해
     실제 `200 OK` + 의미 있는 스타일 태그 응답을 확인.
     수정: `app/core/config.py`, `.env.example`, `.env`.
   - **결제 미연결 확인**: `gemini-3.1-flash-image`(합성 모델)는 여전히 `429
     RESOURCE_EXHAUSTED`. 모델 엔드포인트에 직접 curl로 재현해 원문 에러를 확인—
     `"Quota exceeded for metric: generate_content_free_tier_requests, limit: 0, model:
     gemini-3.1-flash-image"`. 코드 문제가 아니라 이 API 키가 속한 프로젝트에 결제가
     연결되지 않아 무료 티어 quota가 0인 것. 3회 재시도 후 `FAILED`(`PROVIDER_ERROR`,
     retryable)로 정상 종료되는 것도 확인 — 에러 처리 자체는 의도대로 동작.
3. 사용자에게 Google Cloud Console에서 결제 연결이 필요함을 안내함.

### 검증

- 위 실제 HTTP 왕복들 자체가 검증. 코드 변경(`gemini_vision_model` 기본값)은 사소해
  기존 pytest 스위트에 영향 없음을 재실행으로 확인할 예정(다음 스텝).

### 남은 일 (이 항목의 후속은 같은 날 아래 두 번째 로그 항목에서 이어짐)

- 사용자가 결제를 연결하면 이미지 합성까지 포함한 전체 Gemini 스모크 테스트 재실행
  (1:1/4:5/9:16, `variationMode` 포함) — `docs/PROJECT_STATUS.md` "다음 작업 후보" 참고.

## 2026-08-22 (2) — 결제 연결 후 Gemini 실제 합성 첫 성공 (claude)

- 시작: 11:15 KST
- 완료: 11:24 KST
- 작업 agent: claude (Sonnet 5)

### 작업 내용

사용자가 "다시 시도해봐, AI 호출 비율을 최대한 줄여서 API 비용을 줄여줘"라고 요청.
비용 절감을 위해 `.env`의 `PROVIDER_MAX_RETRIES`를 `2` → `0`으로 낮춰(실패해도 과금
호출이 3배로 나가지 않도록) 서버 재기동 후 딱 1건씩만 테스트했다.

1. **1차 시도** (배경=이전 세션에서 쓰던 단색 그라디언트 플레이스홀더): 이미지 합성
   자체는 `200 OK`로 성공(이전 세션의 `429`가 사라짐 — 사용자가 그 사이 결제를 연결한
   것으로 보임). 그러나 자체 품질검사 E5가 `PERSON_COUNT_MISMATCH`로 결과를 거부. 거부된
   이미지는 개인정보 설계상 즉시 폐기되어 원인을 직접 볼 수 없었다.
2. 사용자가 실제 강릉 해변 사진(`images.jpg`, 본인이 리포 루트에 추가)을 제공.
3. **2차 시도** (배경=실제 해변 사진): `DONE`, `safety: PASSED`. 결과 이미지를 다운로드해
   육안으로 확인 — 인물이 배경에 자연스럽게 합성됨. **결론: 1차 실패는 코드 버그가
   아니라 비현실적인 플레이스홀더 배경이 자체 품질검사에 걸린 것이었다.**

### 검증

- 실제 HTTP 요청/응답 자체가 검증. 이번 세션 총 과금 호출은 이미지 합성 2회
  (약 $0.134) — 재시도 0으로 제한해 추가 비용 없이 각 1회씩만 나감.

### 남은 일

- `PROVIDER_MAX_RETRIES=0`이 `.env`에 남아 있음 — 운영/일반 사용 복원력이 필요하면
  나중에 다시 올려야 함(코드 기본값은 `2`로 유지됨).
- 4:5/9:16 비율, `variationMode` 조합은 비용 문제로 아직 미검증.

## 2026-08-22 (3) — 합성 프롬프트 v3: 인스타그램 감성 + 포즈·표정 변경 (claude)

- 시작: 11:26 KST
- 완료: 11:33 KST
- 작업 agent: claude (Sonnet 5)

### 작업 내용

사용자 요청: "좀 더 약간 인스타 감성에 맞게, 사람의 포즈와 표정까지 바꿀 수 있게
프롬프트를 수정해줘봐". 기존 `composition_v2.md`의 "Identity preservation" 절은 체형·
외모 보존만 명시했을 뿐 포즈·표정을 원본 그대로 베끼도록 사실상 강제하고 있었다.

`AGENTS.md` 9-5절 규칙대로 기존 파일은 건드리지 않고 `prompts/composition_v3.md`를
새로 추가:
- 새 `## Pose and expression` 섹션 — 동일 인물임을 유지하는 선에서 장면에 맞는 자연스러운
  포즈(몸 틀기, 풍경 응시 등)와 표정(자연스러운 미소 등) 변경을 명시적으로 허용.
- 새 `## Aesthetic direction` 섹션 — 인스타그램풍 색보정(따뜻한 톤, 깊은 하늘·바다색)과
  3분할 구도를 지시하되 "실제 사진처럼 보여야 한다"는 제약을 함께 명시(과도한 필터/
  일러스트화 방지).
- `app/pipeline/prompt.py`의 `PROMPT_VERSION`을 `v2`→`v3`, `COMPOSITION_TEMPLATE`을
  `composition_v3.md`로 변경.
- `docs/PROMPTS.md`에 v3 항목 기록, `docs/AI_API_CONTRACT.md` 예시 응답의 `promptVersion`을
  `v3`로 갱신하고 결과물 톤이 바뀌었다는 설명 추가, `tests/test_api_e2e.py`의
  `promptVersion` 기대값 갱신.

실제 키로 검증(비용 절감을 위해 `PROVIDER_MAX_RETRIES=0` 유지, 1건씩만 시도):
1. 1차: 자체 품질검사 `ANATOMY_ERROR`로 거부 — 포즈 지시가 다양해지며 손/팔 형태가
   부자연스럽게 나올 확률이 다소 올라간 것으로 보임.
2. 사용자에게 "우연인지 확인하려면 재시도(추가 과금)가 필요하다"고 알리고 승인받은 뒤
   같은 프롬프트로 2차 시도: `DONE`/`safety: PASSED`. 자연스러운 미소, 몸을 튼 포즈로
   의도대로 생성됨 (`gemini_result_v3_instagram.png`로 저장).

### 검증

- `.venv/bin/python -m pytest -q` — 99 passed.
- `ruff check .`, `ruff format --check .` — 통과.
- 실제 Gemini 호출 2회로 프롬프트 변경의 실제 효과와 리스크(ANATOMY_ERROR) 둘 다 확인.

### 남은 일

- v3의 `ANATOMY_ERROR` 재현율은 표본 2건 중 1건(50%)뿐이라 구조적 경향인지 불확실 —
  `docs/PROJECT_STATUS.md` "다음 작업 후보 6" 참고. 표본이 쌓이면 포즈 지시를 보수적으로
  조정할지 재검토.

## 2026-08-15 (2) — docker-compose(Redis) 전체 스택 검증 (claude)

- 시작: 23:00 KST
- 완료: 23:10 KST
- 작업 agent: claude (Sonnet 5)

### 작업 내용

같은 날 앞 항목에서 샌드박스에 Docker/Redis가 없어 미완료로 남겼던 1-3(docker-compose
전체 스택 검증)을 사용자가 Docker를 실행한 뒤 재요청해 다시 시도했다.

- `cp .env.example .env` (mock provider, 키 불필요) 후 `docker compose up --build -d` —
  `ai`+`redis` 두 컨테이너 정상 기동.
- `GET /health` → `{"jobStore":"redis", ...}` — 인메모리가 아니라 실제 Redis에 연결됨을 확인.
- `RedisJobStore`를 실행 중인 Redis(localhost:6379, compose 포트 매핑)에 직접 붙여
  `save`/`get`/`find_by_idempotency_key`/`remember_idempotency_key`/`increment_counter`
  (TTL 포함)를 실제 `JobRecord`로 왕복 검증 — 전부 기대대로 동작.
  (`app/jobs/store.py`는 이번에 코드를 바꾸지 않았으므로, 이 검증은 순수하게 "기존 코드가
  실제 Redis에서도 동작하는가"를 확인한 것이다.)
- 얼굴 없는 사진으로 `POST /v1/generations` 호출 → `422 NO_PERSON_DETECTED`, 그 과정에서
  `enforce_session_rate_limit`/`enforce_daily_budget`이 실제로 Redis에 카운터 키
  (`mirigangneung:ai:budget:20260815`, `mirigangneung:ai:rate:172.20.0.1:2026081513`)를
  쓰는 것을 `redis-cli KEYS`로 확인.
- 계약 오류 경로도 컨테이너에 직접 curl: `GET /v1/generations/does-not-exist` → 404
  `JOB_NOT_FOUND`, `photo` 누락 → 422, `AI_API_KEY`가 빈 값일 때 `/v1/meta`가 인증 없이
  200(로컬 개발 모드) — 모두 계약대로.
- `docker compose logs ai`로 로그에 이미지 바이트·파일명·얼굴 데이터가 없는 것 확인.
- 검증 후 `docker compose down`으로 정리.

### 시도했지만 이번에도 완료하지 못한 것

- **실제 얼굴 사진으로 `DONE`까지의 전체 생성 왕복.** 리포에 실제 인물 사진을 의도적으로
  두지 않기 때문에(개인정보 원칙), 합성 단색/노이즈 이미지로는 Haar/YuNet 둘 다 얼굴을
  검출하지 못해 Job 자체가 만들어지지 않는다. 이 부분은 여전히 pytest E2E(얼굴 검출 우회
  fixture)로만 검증된다 — 필요하면 실제 사진을 로컬에 두고 수동으로 확인해야 한다.

### 관련 commit

아직 커밋하지 않음.

### 다음 담당자에게

`docs/PROJECT_STATUS.md`의 "다음 작업 후보" 5번 참고 — 실제 인물 사진으로 전체 왕복을
확인하고 싶으면 로컬에 사진을 하나 두고 `docs/AI_API_CONTRACT.md`의 curl 예시를 그대로
실행하면 된다.

---

## 2026-08-15 — 이미지 생성 AI 파트 발전: 재생성 변형, 비용 표시, YuNet (claude)

- 시작: 시간 미기록
- 완료: 2026-08-15 22:40 KST
- 작업 agent: claude (Sonnet 5)

### 작업 내용

사용자 요청으로 Notion "미리강릉" 프로젝트 페이지(요구사항 정의서 E1~E9, 유저 시나리오,
UI 설계서 재생성 버튼 레퍼런스, 검토 총평)를 다시 확인하고 현재 코드와 대조해 이미지 생성
AI 파트의 발전 계획을 세운 뒤, 사용자 승인을 받아 Phase 1(외부 의존 없이 이 레포 안에서
바로 가능한 항목)을 구현했다.

1. **재생성 시 "구도, 스타일만 살짝 조정" 지원 (요구사항 E4)**
   - UI 설계서 재생성 버튼의 두 옵션 중 "다른 배경 선택"은 이미 지원됐지만, "구도, 스타일만
     살짝 조정"은 프롬프트에 반영할 자리가 아예 없었다.
   - `VariationMode` enum(`same`\|`new_pose`\|`new_mood`) 추가(`app/schemas/generation.py`),
     `POST /v1/generations`에 선택 필드 `variationMode`로 노출(`app/api/routes_generation.py`).
   - `_auto_idempotency_key`에 `variationMode`를 포함시켜, 백엔드가 `idempotencyKey`를 따로
     관리하지 않아도 `new_pose`/`new_mood` 재생성이 자동으로 새 Job이 되게 했다. 반대로
     같은 `variationMode`를 반복 요청하면 여전히 기존 Job을 재사용한다(비용 폭증 방지).
   - `prompts/composition_v2.md` 신규 추가(v1은 그대로 보존 — `AGENTS.md` 9-5절 규칙),
     `## Regeneration variation` 섹션과 `{variation_direction}` 플레이스홀더 추가.
     `app/pipeline/prompt.py::_variation_direction()`이 모드별 지시문을 채운다.
     `PROMPT_VERSION`을 `v1` → `v2`로 올림(`docs/PROMPTS.md`에 사유 기록).
   - `docs/AI_API_CONTRACT.md`에 `variationMode` 필드, curl 예시, `promptVersion` 예시값
     갱신(`v1`→`v2`) 반영 — 백엔드 팀에 전달 필요.

2. **요청 접수 시점 예상 비용 표시 (검토 총평 §2-7)**
   - `ImageCompositionProvider`에 `estimated_cost_usd` 프로퍼티 추가(기본 `None`),
     `GeminiProvider`는 모델별 근사 단가 테이블을, `MockProvider`는 `0.0`을 반환하도록
     오버라이드(`app/providers/base.py`, `gemini.py`, `mock.py`).
   - `POST /v1/generations`가 Job을 만들 때 `runtime.provider.estimated_cost_usd`로
     `estimatedCostUsd`를 즉시 채운다 — 이전에는 합성이 끝나야만 채워졌다. 합성 완료 후
     `runner.py`가 공급자가 실제로 돌려준 값으로 다시 덮어쓴다(보통 동일한 값).
   - `docs/AI_API_CONTRACT.md`의 202 응답 예시와 설명 갱신.

3. **YuNet 얼굴 검출 모델 적용**
   - `models/face_detection_yunet_2023mar.onnx`(opencv_zoo, Apache-2.0, 232KB)를
     `https://github.com/opencv/opencv_zoo`에서 받아 리포에 커밋. `cv2.FaceDetectorYN.create`로
     로드되는 것과 실제 얼굴 검출 경로가 정상 동작하는 것을 스모크 테스트로 확인.
   - `FACE_MODEL_PATH`를 `os.environ.get()` 직접 읽기에서 `app/core/config.py::Settings`로
     옮기고 `resolved_face_model_path` 프로퍼티(리포 루트 기준 상대경로 해석, 다른
     `prompts_dir`/`backgrounds_dir`와 같은 패턴)를 추가했다 — **기존 코드는 로컬
     `python main.py` 실행 시 `.env`의 `FACE_MODEL_PATH`가 실제로 적용되지 않는 버그가
     있었다**(pydantic-settings의 `.env` 파싱은 실제 프로세스 환경변수를 건드리지 않는데,
     `os.environ.get()`은 실제 환경변수만 본다). Docker(`env_file: .env`)에서는 우연히
     동작했지만 로컬 실행에서는 항상 Haar cascade로 조용히 폴백하고 있었다.
   - `.env.example`의 `FACE_MODEL_PATH` 기본값을 커밋된 모델 경로로 설정, `Dockerfile`에
     `COPY models ./models` 추가, `README.md`에 환경변수 설명 추가.

### 시도했지만 이 환경에서 완료하지 못한 것

- **docker-compose(Redis 포함) 전체 스택 검증.** 이번 세션의 샌드박스에는 `docker` CLI도
  `redis-server`도 없고, 설치할 sudo 권한도 없었다(`sudo -n true` 실패). 거짓으로 완료
  보고하지 않고 `PROJECT_STATUS.md`에 명확히 남겼다 — Docker가 있는 환경에서 재시도 필요.

### 주요 변경 파일

`app/schemas/generation.py`, `app/api/routes_generation.py`, `app/pipeline/prompt.py`,
`prompts/composition_v2.md`(신규), `app/jobs/store.py`, `app/jobs/runner.py`,
`app/providers/base.py`, `app/providers/gemini.py`, `app/providers/mock.py`,
`app/core/config.py`, `app/pipeline/validate.py`, `models/face_detection_yunet_2023mar.onnx`
(신규), `Dockerfile`, `.env.example`, `README.md`, `docs/AI_API_CONTRACT.md`,
`docs/PROMPTS.md`, `tests/test_pipeline_units.py`, `tests/test_api_e2e.py`,
`tests/test_contract.py`, `tests/test_validate.py`

### 테스트 결과

- `.venv/bin/python -m pytest -q` — 99 passed (2026-08-09 기준 88개 + 이번 세션 추가 11개)
- `.venv/bin/ruff check .` — All checks passed
- `.venv/bin/ruff format --check .` — 53 files already formatted
- 이번 세션에는 `.venv`가 없어 `uv venv .venv --python 3.11` + `uv pip install -r
  requirements.txt -r requirements-dev.txt`로 새로 만들었다.
- Gemini 실제 호출 스모크 테스트는 이번에도 수행하지 않음(`GOOGLE_API_KEY` 없음).

### 관련 commit

아직 커밋하지 않음.

### 다음 담당자에게

`docs/PROJECT_STATUS.md`의 "다음 작업 후보" 참고. `variationMode`/`estimatedCostUsd` 계약
변경을 백엔드 팀에 알려야 한다. Docker가 있는 환경에서 docker-compose 전체 스택 검증이
아직 남아 있다.

---

## 2026-08-09 (2) — 배경 이미지 소싱 구조 재점검 및 수정 (claude)

- 시작: 시간 미기록
- 완료: 2026-08-09 21:10 KST
- 작업 agent: claude (Opus 5)

### 작업 내용

사용자 요청으로 백엔드 구조를 다시 확인해 "장소 사진을 API 호출로 가져오는 구조를
파이프라인이 제대로 반영했는지" 검증했다. 백엔드 `Place`/`PlaceImage` 도메인,
`PlaceService`, `KoreanTourApiClient`, `07_DATA_MODEL.md`를 재조사한 결과 두 가지
불일치를 발견해 수정했다 (상세 근거는 ADR-0002).

1. **ID 불일치**: `CompositionJob.onePickPlaceId`는 백엔드 `Place.id`(UUID)를 가리키는
   FK인데, 이 서비스의 로컬 배경 카탈로그는 `anmok-beach` 같은 임의 슬러그를 키로
   써서 운영 요청과 절대 매칭되지 않았다.
2. **소유권 오해**: 백엔드는 관광지 이미지를 파일로 갖고 있지 않다 —
   `Place.thumbnailUrl`/`PlaceImage.imageUrl`은 한국관광공사가 호스팅하는 원격 URL
   문자열이다. "이 서비스가 배경 사진을 갖고 있어야 한다"는 원래 설계 전제가 틀렸다.

수정 내용:

- `app/places/backgrounds.py` 전면 재작성: `get_place`/`load_background_image`를
  `get_dev_place`/`load_dev_background_image`로 이름을 바꿔 로컬 개발·mock 전용임을
  명시. `resolve_place_context()` 추가 — 백엔드가 보낸 `placeName`/`placeRegion`/
  `placeDescription`을 우선 활용.
- `assets/backgrounds/backgrounds.json`: 라이선스 미확인 상태를 반영해 전 항목
  `usable: false`로 고정 (기존엔 `usable: true` + `license: "TBD"`로 자체 모순이었음).
- `app/api/routes_generation.py`: `placeName`/`placeRegion`/`placeDescription`
  선택 필드 추가, `_resolve_background()`로 배경 해석을 Job 생성 전 동기 검증으로
  이동. 실 프로바이더인데 실제 배경이 없으면 `BACKGROUND_REQUIRED`(신규 오류 코드)로
  명확히 실패 — 예전엔 조용히 플레이스홀더 그라디언트로 대체됐다.
- `app/jobs/store.py`: `JobRecord`에 `place_name`/`place_region`/`place_description`
  추가, `background_key`는 이제 제출 시점에 항상 채워짐.
- `app/jobs/runner.py`: `_load_background()` 제거(더 이상 필요 없음), Job 종료 시
  `background_key`도 `input_key`와 함께 즉시 삭제하도록 정리 로직 확장.
- `docs/AI_API_CONTRACT.md`, `README.md`, ADR-0002 갱신.

### 주요 변경 파일

`app/places/backgrounds.py`, `app/api/routes_generation.py`, `app/jobs/store.py`,
`app/jobs/runner.py`, `app/pipeline/prompt.py`, `app/core/errors.py`,
`assets/backgrounds/backgrounds.json`, `docs/AI_API_CONTRACT.md`,
`docs/adr/0002-background-image-sourcing.md`, 관련 테스트 다수

### 테스트 결과

- `pytest -q` — 88 passed (기존 81개 + 이번 작업에서 추가 7개)
- `ruff check .` — All checks passed
- `ruff format --check .` — 51 files already formatted

### 관련 commit

아직 커밋하지 않음.

### 다음 담당자에게

`docs/PROJECT_STATUS.md`의 "백엔드/프론트 팀에 전달할 것" 섹션 참고. 백엔드
`HttpAiGenerationClient` 구현 시 `Place` 이미지 forwarding이 5번째 필수 변경사항으로
추가됐다.

---

## 2026-08-09 — 초기 서비스 구축 (claude)

- 시작: 시간 미기록
- 완료: 2026-08-09 19:50 KST
- 작업 agent: claude (Opus 5)

### 작업 내용

Notion 프로젝트 페이지와 백엔드/프론트엔드 자매 리포를 조사해 이 리포가 채워야 할
자리(백엔드 `AiGenerationClient` 구현체 부재)를 확인하고, 사진 합성 AI 서비스를
처음부터 구축했다.

- FastAPI 기반 비동기 Job 서비스 골격 (`app/main.py`, `app/api/`)
- Job 상태 저장소: Redis 우선 + 인메모리 폴백 (`app/jobs/store.py`)
- 파이프라인 6단계: 검증(B3/B4) → 전처리(B5, EXIF/GPS 제거) → 스타일분석(B6) →
  합성(E1~E4) → 안전성검사(E5) → 마감(E4/E6/E9)
- Provider 어댑터: Gemini(`google-genai` 2.17.0) + Mock, `ImageCompositionProvider`
  ABC 뒤에 감싸 교체 가능하게 구성
- 얼굴 검출: OpenCV Haar cascade 기본 + YuNet 선택적 지원
- 비용·남용 제어: 멱등키 캐시, 일별 예산, 세션별 rate limit
- 오류 코드 19종 + retryable 플래그를 백엔드 재시도 정책과 정렬
- 백엔드 계약 문서(`docs/AI_API_CONTRACT.md`), ADR-0001, AGENTS.md, README

### 주요 변경 파일

리포 전체가 신규 생성. 핵심: `app/jobs/runner.py`, `app/pipeline/*.py`,
`app/providers/gemini.py`, `app/providers/mock.py`, `app/api/routes_generation.py`,
`docs/AI_API_CONTRACT.md`

### 테스트 결과

- `pytest -q` — 81 passed
- `ruff check .` — All checks passed
- `ruff format --check .` — 45 files already formatted
- `docker build .` — 성공 (약 7분, 대부분 pip install)
- `docker run` 단일 컨테이너 스모크 테스트 — `/health`, `/v1/meta` 200 확인,
  `POST /v1/generations`가 합성 이미지(실제 얼굴 아님)에 대해 `422
  NO_PERSON_DETECTED`를 계약대로 반환하는 것 확인. 로그에 이미지/파일명이 남지
  않는 것 확인.

### 문제와 해결 방법

- `google-genai`를 1.2.0으로 고정했다가 pydantic 버전 충돌 발생 →
  실제 사용 가능한 최신 버전(2.17.0)으로 올리고, 이 환경에 `.venv`를 만들어
  `google.genai.types`를 직접 인터프리터로 열어 `GenerateContentConfig`,
  `ImageConfig`, `Part.from_bytes`, `FinishReason`, `BlockedReason`의 실제 필드를
  확인한 뒤 `providers/gemini.py`를 작성했다. (문서만 보고 짐작하지 않았다.)
- 테스트용 애니메이션 WEBP 픽스처가 색이 비슷해 인코더가 프레임을 병합해버려
  `n_frames=1`이 되는 문제 → 프레임 색을 뚜렷하게 다르게 하고, 검증 로직도
  `is_animated` 속성까지 함께 확인하도록 보강.
- EXIF GPS 픽스처를 `exif[34853] = {...}` 형태로 잘못 만들어 Pillow가 rational 인코딩에서
  터짐 → `exif.get_ifd(0x8825)`로 GPS IFD를 올바르게 구성.
- 이 WSL2 환경의 `~/.docker/config.json`이 `credsStore: desktop.exe`를 가리키는데
  해당 헬퍼가 없어 `docker build`가 실패 → 사용자 전역 설정은 건드리지 않고
  `DOCKER_CONFIG`를 스크래치패드의 빈 config로 스코프해 빌드. `docker build`
  기본 동작이 멀티플랫폼 매니페스트만 내보내고 로컬 이미지 스토어에 로드하지
  않아 `docker run`이 이미지를 못 찾음 → `--load` 플래그로 해결.

### 관련 commit

아직 커밋하지 않음 — 사용자 확인 후 커밋 예정.

### 다음 담당자에게

`docs/PROJECT_STATUS.md`의 "아직 안 된 것" 섹션 참고. 특히 Gemini 실제 키 스모크
테스트와 배경 이미지 라이선스 확보가 남아 있다.
