# MiriGangNeung_Agent

미리강릉 사진 합성 AI 개발 레포지토리

사용자 사진과 강릉 관광지 배경을 합성해 "AI 인생샷"을 만드는 비동기 Job 기반 FastAPI
서비스다. `MiriGangNeung_BackEnd`의 `AiGenerationClient`가 이 서비스를 HTTP로 호출한다.
계약 상세는 [`docs/AI_API_CONTRACT.md`](docs/AI_API_CONTRACT.md), 작업 규칙은
[`AGENTS.md`](AGENTS.md)를 먼저 읽는다.

## 전체 서비스에서의 위치

```
[FrontEnd]  React, Vercel            사진 업로드 · 진행 표시 · 결과/경고 표시
    │  POST /api/v1/compositions (multipart, sessionId 포함) → 1.5초 간격 폴링
    ▼
[BackEnd]   Spring Boot :8080        배경 확정(Type1 사진만) · Job 기록 · 결과 보관(TTL)
    │  POST /v1/generations → 2초 간격 상태 폴링 → 완료 시 결과 이미지 다운로드
    ▼
[Agent]     FastAPI :8100  ← 이 레포  검증 → 분석 → 합성 → 품질검사 → 마감
    │
    ▼
[Google Gemini API]                  스타일 분석 · 이미지 합성 · 품질 검사
```

프론트는 이 서비스를 직접 부르지 않는다. 항상 백엔드를 거친다. 이 서비스가 외부에
열려 있을 필요가 없어서, 배포 시에도 내부망에서만 접근하게 둔다(`~/miri-deploy` 구성 참고).

## 실행 (로컬)

Python 3.10 이상.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
cp .env.example .env
.venv/bin/python main.py
```

기본값(`AI_PROVIDER=mock`, `REDIS_HOST=` 비움)으로는 **Gemini API 키나 Redis 없이도**
전체 파이프라인이 인메모리로 동작한다. `http://localhost:8100/docs`에서 API를 확인할 수 있다.

실제 Gemini 합성을 쓰려면 `.env`에서:

```
AI_PROVIDER=gemini
GOOGLE_API_KEY=<발급받은 키>
```

## 실행 (Docker Compose)

```bash
cp .env.example .env
docker compose up --build
```

`ai`(포트 8100, 이 서비스)와 `redis` 두 컨테이너가 뜬다.
`http://localhost:8100/health`로 헬스체크한다.

## API 개요

Base path `/v1`. 모든 요청에 `X-API-Key` 헤더가 필요하다(로컬 개발 시 `AI_API_KEY`를
비워두면 인증을 건너뛴다).

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/v1/generations` | 사진+배경 업로드, Job 생성 (202) |
| GET | `/v1/generations/{id}` | Job 상태 조회 |
| GET | `/v1/generations/{id}/result` | 결과 이미지 다운로드 |
| POST | `/v1/generations/{id}/cancel` | 취소 |
| GET | `/health` | 헬스체크 (인증 불필요) |
| GET | `/v1/meta` | provider/model/지원 비율 등 |

전체 필드와 오류 코드는 [`docs/AI_API_CONTRACT.md`](docs/AI_API_CONTRACT.md) 참고.
`onePickPlaceId`는 백엔드 `Place.id`(UUID)이고, `background`는 백엔드가
`Place.thumbnailUrl`/`PlaceImage.imageUrl`(한국관광공사 이미지)에서 가져와 함께 보내야
한다 — `AI_PROVIDER=mock`일 때만 생략 가능하다.

```bash
curl -H "X-API-Key: $AI_API_KEY" \
     -F photo=@tests/fixtures/person.jpg \
     -F onePickPlaceId=9c1d4f2e-58a1-4b3a-9d2e-1f6a2b7c9d10 \
     -F aspectRatio=4:5 \
     http://localhost:8100/v1/generations
```

## 파이프라인

`POST /v1/generations` 요청 하나가 아래 단계를 거친다 (`app/jobs/runner.py`).
Job 상태는 `QUEUED → ANALYZING → COMPOSITING → QUALITY_CHECK → DONE | FAILED`다.

```
[요청 접수 · 동기]  검증(B3/B4) → 전처리(B5) → 세션 rate limit · 일일 예산 확인 → Job 생성(202)
        │
[ANALYZING]        스타일 분석(B6)
        │
[COMPOSITING]      장소 컨텍스트 결정 → 배경 비율 맞춤 → (필요 시) 얼굴 참조 → 프롬프트 조립
                   → 합성 → 얼굴 유사도 판정 → 미달이면 재합성 (최대 3회)
        │
[QUALITY_CHECK]    품질·안전성 검사(E5) → 경고 수집
        │
[DONE]             마감(E6/E9) → 결과 저장 · 입력 원본 즉시 삭제(B5)
```

**요청 접수 (동기).** 검증·전처리는 Job을 만들기 전에 실행되어, 부적절한 사진은 즉시
4xx로 차단된다(B4). 얼굴이 없거나(`NO_PERSON_DETECTED`) 여러 명이거나(`MULTIPLE_PERSONS`),
너무 흐리거나 가려진 사진, 형식·용량 위반이 여기서 걸린다. 통과하면 EXIF/GPS를 제거하고
긴 변 1536px로 줄인 PNG로 정규화한다. 이어서 `sessionId`별 시간당 횟수
(`RATE_LIMIT_PER_SESSION_PER_HOUR`, 기본 10)와 일일 총량(`DAILY_GENERATION_BUDGET`,
기본 500)을 확인해 넘으면 `RATE_LIMITED` / `BUDGET_EXCEEDED`(429)로 거절한다.
`sessionId`가 없으면 호출자 IP로 대체하는데, 이 서비스를 부르는 것은 백엔드 한 대뿐이라
전 사용자가 카운터를 공유하게 된다 — 그래서 프론트가 브라우저 세션 ID를 항상 보낸다.

**장소 컨텍스트 결정.** 배경 사진에 대해 "어디에 서고, 얼마나 크게, 어떤 빛인지"를 정한다.
우선순위는 ① `assets/places/place_insights.json`(오프라인 VLM 사전 분석, 원본 사진 URL로
매칭) → ② 개발용 카탈로그 → ③ 위 둘이 모두 없을 때만 이번 요청의 배경을 Gemini vision으로
실시간 분석 → ④ 백엔드가 준 텍스트 필드 → ⑤ 범용 문구다. **요청 경로의 AI 판정은 이
③ 폴백 하나뿐이고, 사전 분석이 있는 장소는 vision 호출이 늘지 않는다.**
그 위에 사람이 결과를 보고 쓴 **사진 단위 배치 보정**(`assets/places/placement_overrides.json`)이
있으면 설 자리·크기·가림 요소·포즈 지침을 덮어쓴다 — 분석값이 한 사진에서 서로 충돌해
난간을 관통하는 식의 결과가 반복될 때 그 사진 하나만 바로잡는 용도다(분석 스크립트가
덮어쓰지 않는다).

**배경 비율 맞춤.** 3:2 가로 관광 사진으로 4:5 세로를 만들라고 하면 모델이 프레임의
상당 부분을 지어내 질감이 뭉개진다. 그래서 출력 비율로 먼저 잘라서(`subject_zone` 위치를
살려서) 넘긴다.

**프롬프트 조립.** `prompts/composition_v7.md`에 장소 컨텍스트를 채운다. 핵심 규칙:
배경 픽셀 보존, 밟을 수 있는 표면에만 배치, 7~7.5등신 인체 비율, 장면 조명·색감 일치,
얼굴 보존 최우선. 카메라가 eye-level이면 지평선 위치와 인물 크기(%)로 머리·발의 화면
위치를 **수치로 계산해 주입**한다(`_perspective_anchor()`) — 풍경에 기준 물체가 없어도
성립하는 크기 앵커다. 근접한 랜드마크(버스정류장·아치·등대)의 화면상 크기는 인물 크기
기준이 아니며, 장면의 다른 곳에 있는 난간을 인물 위치로 복제하지 않는다. 버전별
변경 사유는 [`docs/PROMPTS.md`](docs/PROMPTS.md).

**얼굴 신원 재합성.** 생성은 확률적이라 같은 입력도 매번 다른 얼굴이 나온다. 합성 결과를
로컬 SFace 임베딩으로 업로드 사진과 비교해(`FACE_SIMILARITY_TARGET` 0.45) 미달이면 다시
뽑는다(최대 `FACE_REGENERATE_MAX_ATTEMPTS`=3). 판정이 로컬 CPU라 vision 호출은 늘지 않고
이미지 생성 호출만 늘어난다. 상한까지 가면 가장 닮은 결과를 채택한다. 얼굴이 작게 찍힌
사진(`FACE_RATIO_ASSIST_BELOW` 미만)에는 얼굴만 잘라 확대한 참조 이미지를 한 장 더 넘긴다.
인식 모델이 없으면 이 단계만 생략되고 합성은 1회로 끝난다.

**품질·안전성 검사.** 결과 이미지·원본 배경·업로드 인물 사진을 함께 Gemini vision에 넘겨
얼굴 보존, 인체 비율, 배경 보존, 인물–배경 스케일, 신체 결손, 유해성을 본다.
**거부**(`SAFETY_REJECTED_OUTPUT`, 자동 재시도 없음)와 **경고**(결과는 주고 문구만 붙임)를
구분한다. `FACE_NOT_PRESERVED`·`BACKGROUND_ALTERED`는 정상 사용자가 대량으로 막히는 것을
피하려고 경고로만 내려보낸다. 검사기 자체가 장애면 거부하지 않고 `UNKNOWN`으로 통과시킨다.

**마감.** 출력 비율로 정리하고 메타데이터(`provider`, `model`, `promptVersion`, 장소 ID)를
기록한다. 원본 인물 사진과 배경은 Job이 끝나는 즉시(성공·실패·취소 무관) 삭제한다.

## 배경 사진 선정 원칙

- 합성에는 한국관광공사 **Type1**(출처 표시만, 변경 허용) 사진만 쓴다. Type3(변경 금지)는
  백엔드가 걸러서 넘기지 않는다.
- 사용자에게 노출하는 장소·사진은 `assets/places/viable_places.json`이 정한다. 사전 분석에서
  ① 인물 촬영 적합도가 `low`가 아니고 ② 드론 항공샷(`high-angle`)이 아니며 ③ 두 발로 설
  표면이 있는 사진만 남긴다. 이 파일은 `scripts/export_place_filter.py`가 생성하고 백엔드가
  `viable-places.json`으로 복사해 쓴다(단일 원천, 직접 편집 금지 — ADR-0007).
- 원본 사진 자체에 있는 특성(예: 광각 로우앵글로 기울어진 건물)은 "배경을 그대로 쓴다"는
  원칙에 따라 합성이 바꾸지 않는다. 그런 사진이 문제라면 프롬프트가 아니라 사진 선정에서
  거른다.

## 프로젝트 구조

```text
app/
├── core/        # 설정, 오류 코드, 인증, 로깅(개인정보 필터), 비용 제어
├── api/         # FastAPI 라우트, 런타임 배선
├── schemas/     # 백엔드 계약과 1:1 대응하는 Pydantic 모델
├── jobs/        # JobStore(Redis/인메모리), 비동기 실행기
├── pipeline/    # 검증/전처리/스타일분석/프롬프트/합성/안전성/마감
├── providers/   # Provider 어댑터 (gemini / mock) — 새 공급자는 여기만 구현
├── places/      # 관광지 배경 카탈로그 + VLM 사전 분석 리포트 로더
└── storage/     # 임시 이미지 저장 + TTL 정리
prompts/         # 프롬프트 원문 (버전별 .md)
scripts/         # 요청 경로와 분리된 오프라인 배치 도구 (예: analyze_top_places.py)
assets/backgrounds/  # 배경 이미지 카탈로그 (실제 이미지 파일은 커밋하지 않음)
assets/places/       # 장소 특징 VLM 사전 분석 산출물 (place_insights.json)
docs/            # AI_API_CONTRACT, PROJECT_STATUS, WORK_LOG, adr/
tests/
```

## 장소 특징 사전 분석 (선택)

`resolve_place_context()`는 백엔드가 보내는 `placeDescription` 대신, Type1(변경 허용)
이미지가 가장 많은 상위 10개 장소를 VLM으로 미리 분석해둔 리포트
(`assets/places/place_insights.json`)를 우선 사용한다. 상세: `docs/adr/
0003-place-image-vlm-analysis.md`.

```bash
export HF_TOKEN=<huggingface.co에서 무료 발급>
.venv/bin/python scripts/analyze_top_places.py \
    --backend-base-url http://localhost:8080 \
    --top-n 10 --images-per-place 5
```

이 스크립트는 요청 처리 경로와 분리된 오프라인 도구다 — 실행하지 않아도, 또는
결과 파일이 비어 있어도 서비스는 정상 동작한다(다음 우선순위로 폴백). VLM은 로컬이
아니라 Hugging Face 원격 Inference API를 호출하므로 GPU/대용량 RAM이 필요 없다.

## 테스트

```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
```

## 환경변수

전체 목록은 [`.env.example`](.env.example)이 기준 문서다. 주요 변수:

- `AI_API_KEY` — 백엔드와 공유하는 인증 키. 비우면 로컬 개발 모드(인증 생략).
- `AI_PROVIDER` — `gemini` | `mock`
- `GOOGLE_API_KEY`, `GEMINI_IMAGE_MODEL`, `GEMINI_VISION_MODEL`
- `REDIS_HOST` — 비우면 인메모리 JobStore로 폴백
- `DAILY_GENERATION_BUDGET`, `RATE_LIMIT_PER_SESSION_PER_HOUR` — 비용·남용 제어
- `FACE_RECOGNITION_MODEL_PATH` — 얼굴 **신원** 판정 모델(SFace, opencv_zoo, Apache-2.0).
  38MB라 리포에 커밋하지 않으므로 `scripts/download_models.sh`로 받는다. **없어도 서비스는
  동작한다** — 합성 결과가 업로드한 본인인지 확인하고 아니면 다시 뽑는 단계만 생략되고,
  합성은 1회로 끝난다. 상세는 `docs/adr/0005-face-identity-preservation.md`.
- `FACE_SIMILARITY_TARGET`(0.45) / `FACE_SIMILARITY_WARN_BELOW`(0.30) / 
  `FACE_REGENERATE_MAX_ATTEMPTS`(3) — 얼굴 신원 유사도 임계값과 재생성 상한.
  `target`에 못 미치면 다시 뽑고, 상한을 다 쓰고도 `warn_below`에 못 미치면 결과는
  주되 경고를 단다. 거부하지 않는다.
- `FACE_MODEL_PATH` — 얼굴 검출 모델(B3/B4). `models/face_detection_yunet_2023mar.onnx`
  (YuNet, [opencv_zoo](https://github.com/opencv/opencv_zoo) 제공, Apache-2.0)을 리포에
  커밋해 뒀고 기본값도 그쪽을 가리킨다. 비우면 OpenCV 번들 Haar cascade로 폴백한다
  (추가 파일은 필요 없지만 정확도가 낮다). 모델 로드에 실패해도 자동으로 Haar로 폴백한다.
