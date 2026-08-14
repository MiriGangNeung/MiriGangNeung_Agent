# Work Log

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
