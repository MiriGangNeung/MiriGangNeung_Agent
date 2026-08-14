# ADR-0001: 이미지 모델 Provider와 백엔드 전송 방식

- 상태: 승인됨
- 날짜: 2026-08-09

## 배경

`MiriGangNeung_BackEnd`의 `AiGenerationClient`는 인터페이스만 있고 구현체가 없다
(`09_AI_INTEGRATION.md`: "AI Provider/모델은 아직 미정, 백엔드가 임의 선택하지 않는다").
이 리포가 그 자리를 채워야 하며, 두 가지를 결정해야 했다.

1. 어떤 이미지 생성 모델/공급자를 쓸 것인가.
2. 사용자 사진을 백엔드와 어떻게 주고받을 것인가.

이 머신에는 GPU가 없어 로컬 디퓨전(SDXL 등)은 개발·테스트가 불가능하다.

## 결정

### 1. Provider: Google Gemini 이미지 모델 + 어댑터 구조

- 기본 모델: `gemini-3.1-flash-image` (Nano Banana 2). 고품질이 필요하면
  `gemini-3-pro-image`로 환경변수만 바꿔 전환 가능.
- `app/providers/base.py`의 `ImageCompositionProvider` ABC 뒤에 감싼다. 검토 총평
  §3-5(외부 공급자 의존도)가 지적한 대로, 다른 공급자로 교체할 때 파이프라인 코드를
  건드리지 않도록 하기 위함.
- 개발/테스트/CI용으로 `app/providers/mock.py`를 항상 함께 유지한다. API 키나 비용
  없이 전체 파이프라인(Job 상태 전이, 오류 처리, 계약 스키마)을 검증할 수 있다.

**근거**: 지원 비율에 1:1/4:5/9:16이 모두 포함되어 요구사항 E4를 그대로 충족하고,
생성 결과에 SynthID 워터마크가 자동 삽입되어 요구사항 E6(AI 생성 표시)의 절반을
공급자가 처리해 준다. `google-genai` SDK가 멀티 이미지 입력(인물+배경)과 비동기
호출을 모두 지원한다.

**대안**: OpenAI `gpt-image-1`(인물 동일성 보존에 별도 튜닝 필요), 로컬 SDXL+IP-Adapter
(GPU 없어 이 환경에서 불가), 멀티 프로바이더 동시 지원(구현량 대비 이득 낮음 — MVP
단계에서는 어댑터 구조만 마련하고 실제 2번째 공급자는 미룬다).

### 2. 전송: multipart 업로드 + 결과 바이트 반환

- `POST /v1/generations`는 `photo`(필수), `background`(선택) 파일을 multipart로 받는다.
- 결과는 `GET /v1/generations/{id}/result`로 바이트 스트림을 돌려준다.
- 백엔드 `AiGenerationRequest.inputStorageKey`는 그대로 쓸 수 없다 (별도 프로세스라
  로컬 디스크 키를 공유하지 못함) — 백엔드가 `TemporaryImageStorage.open()`으로 읽은
  스트림을 이 서비스에 업로드하는 방식으로 바뀌어야 한다. 상세는
  [`../AI_API_CONTRACT.md`](../AI_API_CONTRACT.md).

**대안**: 공유 볼륨(`IMAGE_TEMP_DIR` 마운트 공유) — 단일 호스트 배포에는 더 간단하지만
백엔드 문서(`10_IMAGE_STORAGE.md`)가 이미 "서버가 다중 인스턴스로 늘어나면 local
filesystem을 쓰면 안 된다"고 명시했으므로 채택하지 않았다. presigned URL —
S3를 MVP에서 명시적으로 제외했으므로(`10_IMAGE_STORAGE.md`) 채택하지 않았다.

## 결과

- 백엔드 쪽에 `HttpAiGenerationClient` 구현 작업이 새로 생긴다 (계약 문서로 전달).
- 이 서비스는 원본 이미지를 자체 임시 저장소에 잠깐 보관했다가 Job 종료 즉시
  삭제한다 (`app/storage/temp_store.py`).
- Provider를 바꾸고 싶을 때는 `app/providers/`에 새 클래스를 추가하고
  `AI_PROVIDER` 환경변수를 바꾸는 것으로 끝난다.
