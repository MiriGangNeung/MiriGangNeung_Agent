Last Updated: 2026-08-24 KST
Last Updated By: claude

# 현재 구현 상태

## 요약

사진 합성 AI 서비스의 전체 파이프라인이 구현되어 있고, mock provider로 E2E가 돈다.
**Gemini provider는 2026-08-22에 실제 키로 스모크 테스트를 마쳤다** — 스타일 분석·합성·
품질검사 전 구간이 실제 호출로 정상 동작함을 확인했다 (아래 "완료된 것" 참고). 다만 1:1
비율 1건만 검증됐고 4:5/9:16, `variationMode` 조합은 비용 문제로 아직 안 돌려봤다.

Notion 프로젝트 문서(요구사항 정의서 E1~E9, UI 설계서 재생성 버튼 레퍼런스, 검토 총평)와
현재 코드를 다시 대조해 두 가지 구현 갭을 메웠다: **재생성 시 "구도, 스타일만 살짝 조정"
옵션**(E4)이 프롬프트에 전혀 반영되지 않았던 것과, **요청 접수 시점 예상 비용 표시**(검토
총평 §2-7)가 없던 것. 또한 얼굴 검출 정확도를 높이기 위해 YuNet ONNX 모델을 리포에 커밋해
기본값으로 연결했다. 상세는 `docs/WORK_LOG.md` 2026-08-15 항목 참고.

백엔드 `Place`/`PlaceImage` 도메인을 다시 확인해 **배경 이미지 소싱 구조를 바로잡았다**
(ADR-0002). 관광지 사진은 백엔드가 파일로 갖고 있지 않고 한국관광공사가 호스팅하는
원격 URL만 DB에 저장한다는 것, 그리고 `onePickPlaceId`가 임의 슬러그가 아니라 백엔드
`Place.id`(UUID)라는 것을 확인했다. 이에 맞춰 `background`를 실 프로바이더에서는
사실상 필수로 바꾸고(없으면 `BACKGROUND_REQUIRED`로 명확히 실패), 로컬 배경 카탈로그는
`AI_PROVIDER=mock` 전용으로 용도를 명확히 했다.

이어서 Tour API의 저작권 유형 코드(`cpyrhtDivCd`/`copyrightCode`)가 `Type1`(출처표시만,
변경 허용)과 `Type3`(변경금지) 두 가지뿐이라는 것을 확인해, AI 합성에는 `Type1`만 쓸 수
있다는 제약을 계약 문서에 명시했다. 또한 백엔드가 이제 장소당 여러 장의 갤러리 이미지를
갖고 있다는 점을 활용해, Type1 이미지가 가장 많은 상위 10개 장소를 Hugging Face 무료
VLM으로 오프라인 사전 분석해 장면·조명·분위기 리포트를 만드는 배치 파이프라인을 추가했다
(ADR-0003). 이 리포트는 `resolve_place_context()`가 백엔드의 짧은 `placeDescription`보다
우선해서 쓴다.

## 완료된 것

- FastAPI 앱 골격, 라이프사이클(정리 루프 포함), 헬스체크/메타 엔드포인트
- `POST/GET/cancel /v1/generations`, `GET .../result` — 계약대로 동작
- Job 상태 저장소: Redis 우선, 인메모리 폴백 (`app/jobs/store.py`)
- 파이프라인 6단계 전부 구현: 검증(B3/B4) → 전처리(B5) → 스타일분석(B6) →
  합성(E1~E4) → 안전성검사(E5) → 마감(E4/E6/E9)
- 얼굴 검출: OpenCV Haar cascade 기본, `FACE_MODEL_PATH` 지정 시 YuNet으로 전환
- Gemini provider (`google-genai` 2.17.0 기준 API 확인 완료) + Mock provider
- 비용·남용 제어: 멱등키 기반 중복 요청 캐시, 일별 예산 상한, 세션별 rate limit
- 오류 코드 20종(`BACKGROUND_REQUIRED` 포함) + retryable 플래그, 백엔드 재시도 규칙과 정렬
- 개인정보: EXIF/GPS 제거, 원본+배경 즉시 삭제, 결과 TTL 정리, 로그 민감정보 필터
- 백엔드 계약 문서(`docs/AI_API_CONTRACT.md`), ADR-0001, ADR-0002, ADR-0003
- **배경 이미지 소싱 구조 재점검 및 수정** (ADR-0002 참고):
  - `onePickPlaceId` = 백엔드 `Place.id`(UUID)임을 계약에 명시. 이전에는 로컬 카탈로그가
    `anmok-beach` 같은 임의 슬러그를 써서 운영 요청과 절대 매칭되지 않는 상태였다.
  - `background`가 없고 개발 카탈로그에도 매칭이 없으면, 실 프로바이더(mock 아닌 경우)는
    조용히 플레이스홀더를 쓰는 대신 `400 BACKGROUND_REQUIRED`로 실패한다
    (`app/api/routes_generation.py::_resolve_background`, Job 생성 전 동기 검증).
  - `placeName`/`placeRegion`/`placeDescription` 선택 필드 추가 — 백엔드가 이미 갖고 있는
    `Place` 정보를 프롬프트 힌트로 바로 활용 (`app/places/backgrounds.py::resolve_place_context`).
  - 로컬 카탈로그(`assets/backgrounds/backgrounds.json`)는 `AI_PROVIDER=mock` 전용으로
    명확히 하고, 라이선스 미확인 상태를 반영해 전 항목 `usable: false`로 고정.
- pytest 전체 통과, ruff lint/format 통과 (정확한 개수는 아래 "테스트 결과" 대신
  `pytest -q` 실행 결과 참고 — 병합 이후 변동이 잦아 여기서는 숫자를 고정하지 않는다)
- Docker 빌드·기동 검증 완료 (단일 컨테이너, mock provider, 2026-08-09 기준): `/health`·
  `/v1/meta` 정상 응답, `POST /v1/generations` 오류 계약 확인, 로그에 이미지/파일명 미노출
  확인.
- **docker-compose(Redis 포함) 전체 스택 검증 완료** (2026-08-15): `docker compose up --build`
  로 `ai`+`redis` 컨테이너 기동. `/health`가 `jobStore: "redis"`로 응답해 실제 Redis에
  연결됨을 확인. `RedisJobStore`를 실행 중인 Redis에 직접 붙여 `save`/`get`/
  `find_by_idempotency_key`/`increment_counter`(TTL 포함)가 코드대로 동작하는 것을 확인.
  얼굴 없는 사진으로 `POST /v1/generations`를 호출해 `enforce_session_rate_limit`/
  `enforce_daily_budget`이 실제 Redis에 카운터 키(`mirigangneung:ai:budget:*`,
  `mirigangneung:ai:rate:*`)를 쓰는 것도 `redis-cli KEYS`로 확인. `GET .../does-not-exist`
  → 404, 사진 누락 → 422, 인증 미설정(`AI_API_KEY` 빈 값) 시 `/v1/meta` 200도 계약대로
  동작. 컨테이너 로그에 이미지 바이트·파일명·얼굴 데이터 미노출 확인.
  **다만 실제 얼굴 사진이 없어(리포에 실제 인물 사진 픽스처를 두지 않음) 컨테이너를 통한
  `DONE`까지의 전체 생성 왕복은 여전히 curl로 검증하지 못했다** — 이 부분은 pytest E2E
  (얼굴 검출 우회 fixture)로만 검증된 상태가 유지된다.
- **재생성 시 "구도, 스타일만 살짝 조정" 지원** (요구사항 E4, 2026-08-15):
  - `POST /v1/generations`에 `variationMode`(`same`\|`new_pose`\|`new_mood`, 기본 `same`)
    선택 필드 추가. UI 설계서 재생성 버튼의 두 옵션 중 "다른 배경 선택"은 이미 지원되던
    것이고, 이번에 남은 "구도, 스타일만 살짝 조정"을 채웠다.
  - `variationMode`가 자동 idempotency 키에 포함되어, 백엔드가 `idempotencyKey`를 따로
    관리하지 않아도 `new_pose`/`new_mood` 재생성이 자동으로 새 Job이 된다.
  - 프롬프트 `composition_v2.md` 신규 추가(v1은 보존), `PROMPT_VERSION`을 `v1` → `v2`로 올림
    (이후 v3로 재차 인상, 아래 참고).
- **요청 접수 시점 예상 비용 표시** (검토 총평 §2-7, 2026-08-15): `estimatedCostUsd`가 이제
  202 응답부터 모델 기준 근사 단가로 채워진다(`ImageCompositionProvider.estimated_cost_usd`
  프로퍼티). 이전에는 합성이 끝나야만 채워졌다.
- **YuNet 얼굴 검출 모델 적용** (2026-08-15): `models/face_detection_yunet_2023mar.onnx`
  (opencv_zoo, Apache-2.0)를 리포에 커밋하고 `.env.example`의 `FACE_MODEL_PATH` 기본값으로
  연결했다. `FACE_MODEL_PATH`를 `app/core/config.py::Settings`로 옮겨 상대경로를 리포 루트
  기준으로 해석하도록(`resolved_face_model_path`) 고쳤다 — 기존에는 `os.environ`에서 직접
  읽어서 로컬 실행(`python main.py`) 시 `.env`의 값이 실제로 적용되지 않는 문제가 있었다.
  Dockerfile에 `COPY models ./models` 추가.
- **실제 인물 사진으로 mock provider `DONE` 전체 왕복 확인** (2026-08-22): 사용자가 제공한
  얼굴 사진(AI로 생성된 인물, AVIF→JPEG 변환)으로 로컬 서버(`python main.py`)에
  `POST /v1/generations`를 실제로 호출해 검증(B3/B4) 통과 → `QUEUED` → 폴링 1회만에
  `DONE`까지 확인. 결과 이미지도 육안으로 확인함.
- **Gemini 키 발급 후 첫 실제 호출 스모크 테스트 및 버그 수정** (2026-08-22): 사용자가
  `GOOGLE_API_KEY`를 발급받아 `AI_PROVIDER=gemini`로 실제 호출.
  - **버그 발견 및 수정**: `GEMINI_VISION_MODEL` 기본값이 `gemini-3.1-flash`였는데, 이 키의
    모델 목록(`GET /v1beta/models`)에 그런 이름이 없어 매 요청 `404`로 실패하고 있었다
    (스타일 분석이 조용히 빈 태그로 폴백되어 겉으로는 안 보였음). 실제 사용 가능한
    `gemini-3.1-flash-lite`로 바꿔 확인 — 이제 실제 호출이 `200 OK`로 성공하고 의미
    있는 스타일 태그(outfit/color/mood/pose/backdrop)가 나온다. `app/core/config.py`,
    `.env.example`, `.env` 수정.
  - **합성 모델(`gemini-3.1-flash-image`)은 여전히 막혀 있음** — 코드 문제가 아니라
    이 키의 프로젝트에 결제(Billing)가 연결되지 않아 무료 티어 quota가 `limit: 0`이라
    Google이 매 요청 `429 RESOURCE_EXHAUSTED`를 반환한다(원문: `"Quota exceeded for
    metric: generate_content_free_tier_requests, limit: 0, model:
    gemini-3.1-flash-image"`). 재시도 3회 후 Job은 `FAILED`(`PROVIDER_ERROR`,
    retryable)로 정상 종료됨 — 에러 처리 자체는 의도대로 동작.
  - 다음 시도 전에 Google Cloud Console에서 이 API 키가 속한 프로젝트에 결제 계정을
    연결해야 한다.
- **Gemini 실제 이미지 합성 첫 성공** (2026-08-22, 결제 연결 후 재시도): 비용 절감을 위해
  `PROVIDER_MAX_RETRIES`를 임시로 `0`으로 낮춰(실패해도 재시도로 과금이 배로 나가지 않게)
  1건만 재시도.
  - 1차 시도(배경=단색 그라디언트 플레이스홀더): 합성 자체(`gemini-3.1-flash-image`)는
    `200 OK`로 성공했지만, 자체 품질검사 E5(`app/providers/gemini.py::check_quality`,
    비전 모델에게 결과 이미지를 다시 보여주고 `person_count` 등을 판정시킴)가
    `PERSON_COUNT_MISMATCH`로 거부. 실패한 이미지는 개인정보 설계상 즉시 폐기되어
    (`app/pipeline/safety.py` 주석 참고) 원인을 직접 들여다볼 수 없었음.
  - 2차 시도(사용자가 제공한 실제 강릉 해변 사진을 배경으로 사용): **`DONE`,
    `safety: PASSED`.** 즉 1차 실패는 코드 버그가 아니라 단색 플레이스홀더가 비현실적인
    합성을 만들어 자체 품질검사에 걸린 것 — 실제 배경 사진을 쓰니 정상 통과함이 확인됨.
  - **결론: Gemini provider 파이프라인 전체(스타일분석→합성→품질검사→완료)가 실제 키로
    처음부터 끝까지 정상 동작함을 확인.**
  - `PROVIDER_MAX_RETRIES`는 테스트 중 비용 절감을 위해 `0`으로 낮췄다가, 테스트가
    끝난 뒤 `.env`에서 다시 기본값 `2`로 복원함(2026-08-22).
- **합성 프롬프트 v3 — 인스타그램 감성 + 포즈·표정 자연스러운 변경** (2026-08-22, 사용자
  요청): `composition_v2.md`는 사실상 원본 사진의 포즈·표정을 그대로 베끼도록 유도했다.
  `composition_v3.md`를 새로 추가해 신원(얼굴·의상·체형)은 유지하되 장면에 맞는 자연스러운
  포즈(살짝 몸 틀기, 풍경 응시 등)와 표정(자연스러운 미소 등)을 명시적으로 허용하고,
  인스타그램풍 색보정·구도 지시를 담은 `## Aesthetic direction` 섹션을 추가했다
  (`PROMPT_VERSION` `v2`→`v3`, 상세는 `docs/PROMPTS.md`).
  - 실제 키로 2회 테스트: 1차는 자체 품질검사에서 `ANATOMY_ERROR`로 거부(포즈 지시가
    다양해지면서 손/팔 형태가 부자연스럽게 나올 확률이 다소 올라간 것으로 보임), 2차는
    같은 프롬프트로 재시도해 `DONE`/`PASSED` — 자연스러운 미소와 몸을 튼 포즈로 정상
    생성됨. 1회성 실패였는지 구조적 경향인지는 표본이 2건뿐이라 단정할 수 없음 —
    "다음 작업 후보"에 추적 항목 추가.
- **장소 특징 VLM 사전 분석 파이프라인** (2026-08-24, ADR-0003 참고):
  - Tour API `cpyrhtDivCd`(→ 백엔드 `copyrightCode`)는 `Type1`(출처표시만, 변경 허용)/
    `Type3`(변경금지) 두 값뿐이라는 것을 공식 매뉴얼로 확인. `docs/AI_API_CONTRACT.md`에
    "배경은 Type1만 forwarding" 제약을 반영.
  - `scripts/analyze_top_places.py`(신규): 백엔드 API에서 Type1 이미지가 가장 많은
    상위 10개 장소를 골라, 장소당 최대 5장을 Hugging Face 무료 Inference API(비전 지원
    채팅 모델)로 분석해 `assets/places/place_insights.json`에 저장하는 오프라인 배치.
    이 개발 환경(RAM 7.5GB, GPU 없음)에서는 로컬 VLM 실행이 사실상 불가능해 원격 호스팅만
    쓴다.
  - `app/places/insights.py`(신규): 런타임 로더. `resolve_place_context()` 우선순위에
    한 단계 추가(개발 카탈로그 → **insights 매칭** → 백엔드 제공 필드 → 범용 문구).
  - `HF_TOKEN`이 없어 배치를 아직 실행하지 못했다 — 커밋된 `place_insights.json`은
    빈 카탈로그다. 서비스는 이 상태에서도 기존 방식대로 정상 동작한다.

## 아직 안 된 것 / 알려진 제약

- **Gemini 이미지 합성은 1:1 비율 1건만 실제 검증됨.** 결제 연결 후 2026-08-22에 실제
  해변 사진을 배경으로 첫 성공(`DONE`, `safety: PASSED`)을 확인했지만, 4:5/9:16 비율과
  `variationMode`(`new_pose`/`new_mood`) 조합은 비용 절감을 위해 아직 시도하지 않았다.
- **배경 이미지 라이선스 확정 전.** `copyrightCode == "Type1"`(변경 허용) 여부는 코드로
  구분할 수 있게 됐지만(ADR-0003), 실제로 그 판단이 한국관광공사 이용 약관과 정확히
  일치하는지, 출처 표기를 어떻게(어디에) 할지는 법무/정책 확인이 필요하며 이 리포의
  범위 밖이다 — 백엔드/기획 팀 확인 필요.
- **`scripts/analyze_top_places.py` 배치를 아직 실행하지 못했다.** `HF_TOKEN`이 없어
  `place_insights.json`이 빈 카탈로그로 커밋돼 있다. 토큰 발급 후 1회 실행하면 상위
  10개 장소 리포트가 채워진다.
- **메트릭/관측성 없음.** 검토 총평 §2-5(제품 분석 이벤트)에 해당하는 부분은 이
  리포 범위 밖으로 남겨뒀다. 필요해지면 별도 작업으로 추가.
- **Docker 컨테이너 안에서는 아직 실제 인물 사진으로 happy path를 확인하지 못했다.**
  2026-08-22에 로컬(`python main.py`, mock provider)에서는 사용자 제공 사진으로 `DONE`까지
  확인했지만, docker-compose 컨테이너 기준으로는 아직이다(이 세션에서 `docker` 명령이
  WSL 셸에 안 잡혀 있었음). 리포에는 실제 얼굴 테스트 픽스처를 두지 않으므로(개인정보
  원칙상 의도적으로 비움), 필요하면 로컬에 실제 인물 사진을 하나 두고
  `docs/AI_API_CONTRACT.md`의 curl 예시를 컨테이너 대상으로 실행해 본다.
- **실제 `Place` 데이터로 background/placeName forwarding을 검증하지 못했다.** 백엔드의
  `HttpAiGenerationClient`가 아직 구현되지 않아, 이 서비스 쪽 로직(`_resolve_background`,
  `resolve_place_context`)은 유닛/E2E 테스트로만 검증됐다. 백엔드 구현 후 실제 연동
  테스트가 필요하다.

## 백엔드/프론트 팀에 전달할 것

- `docs/AI_API_CONTRACT.md` — 백엔드 `HttpAiGenerationClient` 구현에 필요한 전체 계약.
  **5가지 변경사항**(문서 상단): 구현체 추가, 빈 블록 채우기, 폴링 스케줄러, 결과 저장,
  **그리고 `Place.thumbnailUrl`/`PlaceImage.imageUrl`에서 이미지를 가져와 `background`로
  forwarding**(신규 — ADR-0002).
- `onePickPlaceId`로 반드시 `Place.id`(UUID)를 보내야 한다. 슬러그나 `tourContentId`가
  아니다.
- 가능하면 `placeName`/`placeRegion`/`placeDescription`도 함께 보내 달라 — 프롬프트
  품질에 직접 영향을 준다.
- **배경 이미지는 반드시 `copyrightCode == "Type1"`인 것만 forwarding해야 한다**
  (`Type3`은 변경금지라 AI 합성에 쓸 수 없다). `GET /api/v1/places/{id}`의
  `images[].copyrightCode`로 이미 판단 가능하다.
- **(2026-08-15) `variationMode` 선택 필드.** 프론트의 재생성 버튼이 "구도, 스타일만
  살짝 조정"을 요청하면 `new_pose` 또는 `new_mood`를 보내면 된다. `idempotencyKey`를 따로
  주지 않아도 자동으로 새 Job이 된다. `promptVersion`이 `v1`에서 `v3`으로 바뀌었으니
  프론트/백엔드가 이 값으로 분기하는 로직이 있다면 갱신 필요.
- **(2026-08-15) `estimatedCostUsd`가 202 응답부터 채워진다.** 이전에는 `DONE` 이후에만
  값이 있었다.

## 다음 작업 후보

1. ~~Google Cloud Console에서 결제 연결~~ — 완료 (2026-08-22), 1:1 비율 실제 합성 성공
   확인. 남은 건 4:5/9:16 비율과 `variationMode`(`new_pose`/`new_mood`) 조합 검증 —
   호출 1회당 약 $0.067이므로 필요할 때만 추가로 진행.
2. 백엔드 `HttpAiGenerationClient` 구현 후 실제 `Place` 데이터로 통합 테스트
3. Tour API 이미지의 AI 합성 배경 사용 가능 여부 법무/정책 확인 (Type1 판단이
   실제 이용 약관과 일치하는지, 출처 표기 방식)
4. 검토 총평 §2-7의 "저해상도 프리뷰 → 고해상도 생성" 흐름 도입 여부 검토 — 1번(결제
   연결 후 실제 이미지 합성) 결과를 보고 비용 대비 UX 이득 판단
5. (선택) docker-compose 컨테이너 환경에서도 실제 인물 사진으로 `DONE`까지 curl 검증
   (로컬 `python main.py` 기준으로는 2026-08-22에 확인 완료)
6. **v3 프롬프트의 `ANATOMY_ERROR` 재현율 추적.** 2건 중 1건에서 발생(50%)했는데
   표본이 너무 작아 구조적 경향인지 판단 불가. 표본을 더 쌓아 재현율이 눈에 띄게
   높으면(예: >20%) `## Pose and expression` 섹션에서 "손을 주머니에" 같은 손이
   복잡하게 나오는 포즈 예시를 빼는 등 지시를 보수적으로 조정 검토.
7. `HF_TOKEN` 발급 후 `scripts/analyze_top_places.py` 실행해 `place_insights.json`
   실제 채우기, 결과 리포트 품질 수동 검수
