Last Updated: 2026-08-09 21:10 KST
Last Updated By: claude

# 현재 구현 상태

## 요약

사진 합성 AI 서비스의 전체 파이프라인이 구현되어 있고, mock provider로 E2E가 돈다.
Gemini provider는 실제 API 호출 코드까지 작성됐지만 **실제 키로 스모크 테스트는
아직 수행하지 않았다** (`GOOGLE_API_KEY` 없음).

백엔드 `Place`/`PlaceImage` 도메인을 다시 확인해 **배경 이미지 소싱 구조를 바로잡았다**
(ADR-0002). 관광지 사진은 백엔드가 파일로 갖고 있지 않고 한국관광공사가 호스팅하는
원격 URL만 DB에 저장한다는 것, 그리고 `onePickPlaceId`가 임의 슬러그가 아니라 백엔드
`Place.id`(UUID)라는 것을 확인했다. 이에 맞춰 `background`를 실 프로바이더에서는
사실상 필수로 바꾸고(없으면 `BACKGROUND_REQUIRED`로 명확히 실패), 로컬 배경 카탈로그는
`AI_PROVIDER=mock` 전용으로 용도를 명확히 했다.

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
- 백엔드 계약 문서(`docs/AI_API_CONTRACT.md`), ADR-0001, ADR-0002
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
- pytest 88개 통과, ruff lint/format 통과
- Docker 빌드·기동 검증 완료 (단일 컨테이너, mock provider): `/health`·`/v1/meta` 정상
  응답, `POST /v1/generations` 오류 계약 확인, 로그에 이미지/파일명 미노출 확인.

## 아직 안 된 것 / 알려진 제약

- **Gemini 실제 호출 미검증.** `providers/gemini.py`는 `google-genai` 2.17.0의 실제
  타입을 인터프리터로 직접 확인하고 작성했지만, 실제 이미지 생성 응답 구조는 키 발급
  후 스모크 테스트가 필요하다.
- **배경 이미지 라이선스 확정 전.** 로컬 카탈로그는 개발용일 뿐이고, 운영에서 실제로
  쓰일 배경은 백엔드가 Tour API 이미지를 forwarding하는 경로다. 그 Tour API 이미지가
  AI 합성 배경으로 실제 사용 가능한지(한국관광공사 이용 약관상 출처 표기 조건 등)는
  법무/정책 확인이 필요하며, 이 리포의 범위 밖이다 — 백엔드/기획 팀 확인 필요.
- **YuNet 모델 파일 미포함.** 기본은 OpenCV 번들 Haar cascade로 동작(정확도 낮음).
  운영 배포 전 YuNet ONNX 모델을 받아 `FACE_MODEL_PATH`로 주입하는 것을 권장.
- **메트릭/관측성 없음.** 검토 총평 §2-5(제품 분석 이벤트)에 해당하는 부분은 이
  리포 범위 밖으로 남겨뒀다. 필요해지면 별도 작업으로 추가.
- **docker-compose(Redis 포함) 전체 스택은 아직 검증하지 못했다.**
- **실제 인물 사진으로 Docker 컨테이너 안에서 happy path를 확인하지 못했다.** pytest
  E2E(얼굴 검출 우회 fixture)로만 검증됐다.
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

## 다음 작업 후보

1. `GOOGLE_API_KEY` 발급 후 Gemini 스모크 테스트 (1:1/4:5/9:16 각각, 소요시간 기록)
2. 백엔드 `HttpAiGenerationClient` 구현 후 실제 `Place` 데이터로 통합 테스트
3. Tour API 이미지의 AI 합성 배경 사용 가능 여부 법무/정책 확인
4. `docker compose up`으로 Redis 포함 전체 스택 기동 검증
5. YuNet 모델 파일 주입 여부 결정
