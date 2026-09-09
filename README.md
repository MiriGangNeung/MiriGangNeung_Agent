# MiriGangNeung_Agent

미리강릉 사진 합성 AI 개발 레포지토리

사용자 사진과 강릉 관광지 배경을 합성해 "AI 인생샷"을 만드는 비동기 Job 기반 FastAPI
서비스다. `MiriGangNeung_BackEnd`의 `AiGenerationClient`가 이 서비스를 HTTP로 호출한다.
계약 상세는 [`docs/AI_API_CONTRACT.md`](docs/AI_API_CONTRACT.md), 작업 규칙은
[`AGENTS.md`](AGENTS.md)를 먼저 읽는다.

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

`POST /v1/generations` 요청 하나가 6단계를 거친다 (`app/jobs/runner.py`).

```
검증(B3/B4) → 전처리(B5) → 스타일분석(B6, ANALYZING)
  → 합성(E1~E4, COMPOSITING) → 안전성·품질검사(E5, QUALITY_CHECK) → 마감(E6/E9, DONE)
```

검증·전처리는 Job을 만들기 전에 동기로 실행되어, 부적절한 사진은 즉시 4xx로 차단된다(B4).

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
