# AGENTS.md — MiriGangNeung Agent (사진 합성 AI)

clone 직후에는 이 파일과 `docs/PROJECT_STATUS.md`를 읽는다. 백엔드와의 계약은
`docs/AI_API_CONTRACT.md`가 단일 진실 공급원이다.

## 1. 프로젝트 개요

- 프로젝트 이름: `MiriGangNeung_Agent` / 미리강릉 사진 합성 AI
- 목적: 사용자 사진 + 강릉 관광지 배경을 합성해 "AI 인생샷"을 만드는 비동기 Job 기반
  FastAPI 서비스. 요구사항 정의서의 E1~E9(AI 가상 여행 이미지 생성)와 B3~B6(사진 유효성
  검사·전처리·스타일 분석)을 담당한다.
- 역할: `MiriGangNeung_BackEnd`의 `AiGenerationClient`가 HTTP로 호출하는 별도 서비스다.
  코스 큐레이션(F), 회원(A), 관리자(H) 등은 이 리포의 범위가 아니다.

자매 리포:
- `MiriGangNeung_BackEnd` (Java/Spring): `/api/v1/compositions`를 노출하고, 이 서비스를
  `AI_BASE_URL`로 호출한다. 문서: `MiriGangNeung_BackEnd_Codex_MD_Set/docs/09_AI_INTEGRATION.md`.
- `MiriGangNeung_FrontEnd` (React/TS): 6개 화면 중 `PhotoUpload`/`CompositeResult`가 이
  서비스가 만드는 결과를 직접 소비한다.

## 2. 확정된 기술 스택

- Python 3.11, FastAPI + uvicorn
- Job 상태: Redis 우선, `REDIS_HOST` 비어있으면 인메모리 폴백 (`app/jobs/store.py`)
- 이미지 처리: Pillow, OpenCV(얼굴 검출)
- AI Provider: Google Gemini (`google-genai`), `providers/base.py` 뒤에 어댑터로 감싸져
  있어 다른 공급자로 교체 가능. 개발/CI용 `providers/mock.py`도 있다.
- 새 provider, DB, 메시지 큐를 임의로 추가하지 않는다. 필요하면 먼저 `docs/adr/`에 근거를
  남기고 사용자와 합의한다.

## 3. 작업 시작 전 필수 절차

1. `git status`로 현재 상태를 확인한다.
2. `docs/PROJECT_STATUS.md`로 구현 상태를 확인한다.
3. 요청과 직접 관련된 문서만 읽는다 (`docs/AI_API_CONTRACT.md`, 관련 ADR).
4. 기존 코드(특히 `app/pipeline/`, `app/providers/base.py`)를 먼저 확인한 뒤 구현한다.

## 4. 문서의 역할

- `docs/AI_API_CONTRACT.md`: 백엔드와 합의한 HTTP 계약. **여기를 바꾸면 백엔드 팀에 알려야
  한다.** 상태값·오류코드·재시도 정책이 여기 고정돼 있다.
- `docs/PROJECT_STATUS.md`: 현재 코드가 실제로 하는 일. 과거 상태를 누적하지 않는다.
- `docs/WORK_LOG.md`: 의미 있는 작업의 누적 기록. 기존 기록은 삭제·수정하지 않는다.
- `docs/adr/`: 중요한 아키텍처 결정과 이유.
- `docs/PROMPTS.md`: 프롬프트 버전 이력 요약. 실제 프롬프트 본문은 `prompts/*.md`.

## 5. 파이프라인 구조 (요구사항 매핑)

`app/jobs/runner.py`가 순서대로 실행한다.

1. **검증** (`app/pipeline/validate.py`, B3/B4) — Job 생성 전에 동기로 실행. 잘못된 사진은
   Job을 만들지 않고 즉시 4xx.
2. **전처리** (`app/pipeline/preprocess.py`, B5) — EXIF/GPS 제거, 리사이즈. 검증과 함께
   동기 실행.
3. **스타일 분석** (`app/pipeline/style.py`, B6) — `ANALYZING` 단계. 실패해도 Job을 죽이지
   않고 빈 태그로 진행한다.
4. **합성** (`app/pipeline/compose.py`, E1~E4, E8) — `COMPOSITING` 단계. 타임아웃/일시적
   실패는 제한 횟수 재시도.
5. **안전성·품질 검사** (`app/pipeline/safety.py`, E5) — `QUALITY_CHECK` 단계. 거부는
   **재시도 금지**.
6. **마감** (`app/pipeline/finalize.py`, E4/E6/E9) — 비율 크롭, AI 생성 메타데이터 삽입,
   `DONE`.

새 Provider를 추가할 때는 `app/providers/base.py`의 `ImageCompositionProvider`만
구현하면 되고, 파이프라인 코드는 건드리지 않는다.

## 6. 모호한 요구사항 처리

다음처럼 백엔드와의 API 계약, 상태값, 오류 코드, AI Provider 선택에 영향을 주는 요구는
임의로 결정하지 않는다.

- 문제와 영향 범위를 먼저 명시한다.
- 사용자의 결정을 요청한다.
- 결정을 기다리며 구현해야 하면 결과를 `PROJECT_STATUS.md`/`WORK_LOG.md`에 명확히 남긴다.

단순한 구현 세부사항(내부 함수 분리, 변수명 등)은 합리적으로 처리한다.

## 7. 구현 원칙

- 요청받은 범위에 집중하고 불필요한 리팩토링을 하지 않는다.
- `docs/AI_API_CONTRACT.md`에 정의된 API 계약을 준수한다. 바꿔야 하면 문서를 먼저 갱신하고
  백엔드 팀에 전달할 내용을 명시한다.
- 사용자 사진·EXIF·얼굴 데이터를 로그에 남기지 않는다 (`app/core/logging.py`의 필터가
  1차 방어선이지만, 새 로그를 추가할 때도 이 원칙을 지킨다).
- 원본 이미지는 Job 종료 즉시 삭제, 결과는 TTL 후 삭제한다 (`app/storage/temp_store.py`).
- 안전성 거부(`SAFETY_REJECTED_*`)는 절대 자동 재시도하지 않는다.
- secret, API key를 코드나 커밋에 하드코딩하지 않는다.
- 새 dependency는 필요성을 확인한 뒤 `requirements.txt`(런타임) 또는
  `requirements-dev.txt`(개발/테스트)에 추가한다.

## 8. 테스트 및 검증

작업 종료 전:

```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
```

실패한 테스트를 성공으로 보고하지 않는다. 환경 문제로 실행하지 못했다면 실패인지
미실행인지와 원인을 최종 보고에 구분해서 남긴다. Gemini 실제 호출 스모크 테스트는
`GOOGLE_API_KEY`가 있을 때만 수행하고, 결과는 `docs/WORK_LOG.md`에 소요시간과 함께 기록한다.

## 9. 작업 완료 후 문서 업데이트

의미 있는 작업이 끝나면:

1. `docs/PROJECT_STATUS.md`를 실제 코드와 테스트 결과에 맞게 갱신한다.
2. `docs/WORK_LOG.md`에 작업을 추가한다.
3. 백엔드 계약에 영향이 있으면 `docs/AI_API_CONTRACT.md`를 갱신하고 이를 반드시 알린다.
4. 새롭고 중요한 아키텍처 결정이 있으면 `docs/adr/`에 ADR을 추가한다.
5. 프롬프트를 바꿨으면 `prompts/`에 새 버전 파일을 추가하고(기존 파일 수정 금지),
   `app/pipeline/prompt.py`의 `PROMPT_VERSION`을 올리고 `docs/PROMPTS.md`에 기록한다.

사소한 오타 수정은 WORK_LOG에 남기지 않는다.

시간은 KST(UTC+9)로 기록하고, 과거 작업의 정확한 시간을 확인할 수 없으면 임의로 만들지 않고
"시간 미기록"으로 표시한다.

## 10. Git

작업 시작 전 기존 변경사항을 보존한다. 사용자의 요청 없이 reset·대규모 삭제·기존 변경
덮어쓰기를 하지 않는다. 가능하면 WORK_LOG에 관련 commit hash와 message를 기록한다.

## 11. 문서와 코드가 충돌할 경우

코드가 우선이다. `docs/PROJECT_STATUS.md`가 코드와 다르면 코드를 신뢰하고 문서를 고친다.
단, `docs/AI_API_CONTRACT.md`는 예외다 — 백엔드가 이 문서를 근거로 구현하므로, 코드를
계약에 맞추거나 계약 변경을 먼저 백엔드 팀에 알려야 한다.
