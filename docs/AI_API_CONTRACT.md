# AI 서비스 API 계약

이 문서는 `MiriGangNeung_BackEnd`의 `AiGenerationClient` 구현체(`HttpAiGenerationClient`)가
이 서비스(`MiriGangNeung_Agent`)를 호출할 때 지켜야 할 계약이다. 백엔드 문서
`MiriGangNeung_BackEnd_Codex_MD_Set/docs/09_AI_INTEGRATION.md`와 `06_API_SPECIFICATION.md`에서
정의한 상위 계약을 구체적인 HTTP 스펙으로 채운 것이다.

## 왜 백엔드 코드 변경이 필요한가

현재 백엔드의 `AiGenerationClient` 시그니처는 아래와 같다.

```java
record AiGenerationRequest(String inputStorageKey, String onePickPlaceId, String aspectRatio){}
record AiGenerationResponse(String providerJobId, String status, String imageReference,
                            String safetyStatus, String reasonCode, String error){}
```

`inputStorageKey`는 백엔드 로컬(또는 컨테이너) 디스크의 키다. 이 AI 서비스는 별도 프로세스이므로
그 키로 파일을 읽을 수 없다. 대신 **multipart 업로드 + 결과 바이트 반환** 방식을 쓴다. 백엔드
쪽에 필요한 변경은 5가지다.

1. `HttpAiGenerationClient` 구현체 추가 — `TemporaryImageStorage.open(inputStorageKey)`로 읽은
   스트림을 `POST /v1/generations`에 multipart로 전송한다.
2. `CompositionService.create()`의 빈 `if(ai.isPresent()){}` 블록을 채우고, 응답의
   `providerJobId`를 `CompositionJob`에 저장한다.
3. 상태 폴링 스케줄러 — `GET /v1/generations/{providerJobId}` 결과를 `CompositionStatus`로
   반영한다 (매핑은 아래 표, 값이 1:1이라 새 enum이 필요 없다).
4. `DONE` 상태가 되면 `GET /v1/generations/{providerJobId}/result`로 결과 바이트를 받아
   백엔드 `TemporaryImageStorage`에 저장하고 `resultStorageKey`를 채운다.
5. **배경 이미지 forwarding — 이 서비스는 관광지 사진을 갖고 있지 않다.** `Place.thumbnailUrl` /
   `PlaceImage.imageUrl`은 한국관광공사가 호스팅하는 원격 URL 문자열일 뿐이다
   (`PlaceService.upsert()` 참고, `07_DATA_MODEL.md`의 `Place`/`PlaceImage` 스키마). 백엔드가
   `onePickPlaceId`로 `Place`를 조회해 그 URL에서 이미지 바이트를 가져온 뒤 `POST
   /v1/generations`의 `background` 필드로 함께 보내야 한다. 이 단계 없이는 `AI_PROVIDER=gemini`
   같은 실 프로바이더 요청이 전부 `BACKGROUND_REQUIRED`로 실패한다 (아래 참고).
   **반드시 `copyrightCode == "Type1"`인 이미지만 보내야 한다** — Tour API 저작권 유형
   코드(`cpyrhtDivCd`)는 `Type1`(제1유형, 출처표시만 하면 됨, 변경 허용)과
   `Type3`(제1유형 + 변경금지) 두 가지뿐이고, AI 합성은 원본을 변형하는 행위라 `Type3`
   이미지는 법적으로 배경에 쓸 수 없다. `GET /api/v1/places/{id}`의 `images[].copyrightCode`로
   이미 노출되고 있으니 백엔드가 forwarding 전에 걸러야 한다 (`docs/adr/
   0003-place-image-vlm-analysis.md`). `Type1`이어도 "출처표시-권장"이므로 최종 결과물
   주변에 한국관광공사 출처 표기가 필요하다 — 이건 프론트/백엔드 UI 몫이다.

> **`onePickPlaceId`는 백엔드 `Place.id`(UUID)다.** `CompositionJob.onePickPlaceId`가
> `Place`를 가리키는 FK이기 때문이다 (`07_DATA_MODEL.md`: `Place 1 ─ N CompositionJob`).
> 임의의 사람이 읽을 수 있는 슬러그가 아니다 — 이 서비스의 로컬 개발용 배경 카탈로그
> (`assets/backgrounds/backgrounds.json`)는 이 UUID와 절대 매칭되지 않으며, `AI_PROVIDER=mock`
> 로컬 개발과 curl 수동 테스트에서만 쓰인다.
>
> **다만 백엔드 쪽에 아직 남은 계약상 공백 두 가지를 파악했다** (백엔드
> `docs/superpowers/specs/2026-08-10-tour-photo-source-tabs-design.md` 조사,
> `docs/adr/0004-realtime-background-analysis.md` 참고). 이 AI 서비스는
> `onePickPlaceId`를 불투명한 문자열로만 다루고 `background` 바이트만 신뢰하므로
> 아래 두 가지로 이 서비스가 당장 막히진 않지만, 백엔드 팀이 알아야 할 공백이다.
> 1. 사용자가 "1번 배경 선택 화면"에서 `GET /api/v1/award-photos`/
>    `GET /api/v1/tourism-photos`(공모전 수상작/관광사진갤러리 탭)로 고른 배경은
>    응답 id가 `kto-award:<contentId>`/`kto-gallery:<galContentId>` 형태의 표시용
>    식별자이지 `Place.id`가 아니다. 이 경우 백엔드가 `onePickPlaceId`로 무엇을
>    보내야 하는지 계약에 아직 정의돼 있지 않다.
> 2. `GET /api/v1/tourism-photos`(`TourismPhotoResponse`)에는 `copyrightCode`
>    필드 자체가 없다 — 백엔드도 이 소스에 대해서는 Type1 여부를 판단할 근거가
>    없다는 뜻이다. 위 5번의 "반드시 Type1만" 요구사항을 이 소스에서 지키려면
>    백엔드가 별도로 `cpyrhtDivCd`를 응답에 추가해야 한다.

## 인증

모든 요청에 헤더를 포함한다.

```
X-API-Key: ${AI_API_KEY}
```

값은 백엔드 `.env`의 `AI_API_KEY`와 이 서비스 `.env`의 `AI_API_KEY`가 **동일**해야 한다.
`AI_API_KEY`가 비어 있으면 이 서비스는 로컬 개발 모드로 간주해 인증을 건너뛴다 — 운영
배포에서는 반드시 채워야 한다.

## 상태 매핑

이 서비스의 `status`는 백엔드 `CompositionStatus` enum과 **값이 완전히 동일**하다. 새로운 값을
추가하지 않았으므로 백엔드는 문자열을 그대로 enum으로 파싱하면 된다.

| 이 서비스 `status` | 백엔드 `CompositionStatus` | 의미 |
|---|---|---|
| `QUEUED` | `QUEUED` | 요청 접수, 대기 중 |
| `ANALYZING` | `ANALYZING` | 스타일 분석 중 (B6) |
| `COMPOSITING` | `COMPOSITING` | AI 합성 중 (E1~E4) |
| `QUALITY_CHECK` | `QUALITY_CHECK` | 안전성·품질 검사 중 (E5) |
| `DONE` | `DONE` | 완료, 결과 다운로드 가능 |
| `FAILED` | `FAILED` | 실패, `error` 필드 확인 |

`09_AI_INTEGRATION.md`가 정의한 축약형(`RUNNING|DONE|FAILED`)도 모든 응답에 `coarseStatus`로
함께 실어 보낸다. 두 문서가 서로 어긋나지 않도록 하기 위함이며, 백엔드는 필요한 쪽을 골라 쓰면 된다.

**다인원 사진은 자동으로 잘라낸다.** 얼굴이 둘 이상 검출되면, 가장 큰 얼굴이 두 번째보다
충분히 크고(면적 1.5배 이상) 다른 얼굴을 잘라 낼 수 있을 때 주 피사체만 크롭해서 합성에
쓴다. 그 조건을 만족하지 못할 때만 `MULTIPLE_PERSONS`로 거부한다. 백엔드가 보내는 값은
달라지지 않으며, 크롭 여부는 응답에 별도로 표시되지 않는다.

사진 유효성 검사(B3/B4)는 **Job을 만들기 전에** 동기로 실행된다. 즉 `POST /v1/generations`가
4xx를 반환했다면 Job 자체가 생성되지 않은 것이고, 202를 받았다면 이후 상태는 항상
`QUEUED`부터 시작한다.

## 엔드포인트

Base path: `/v1` (헬스체크만 예외로 루트의 `/health`)

### `POST /v1/generations`

`multipart/form-data`

| 필드 | 필수 | 설명 |
|---|---|---|
| `photo` | 예 | 사용자 사진 파일 (JPG/PNG/WEBP, 최대 10MB) |
| `onePickPlaceId` | 예 | 백엔드 `Place.id` (UUID) |
| `aspectRatio` | 아니오 (기본 `4:5`) | `1:1` \| `4:5` \| `9:16` |
| `variationMode` | 아니오 (기본 `same`) | `same` \| `new_pose` \| `new_mood`. 요구사항 E4 재생성 옵션 중 "구도, 스타일만 살짝 조정"에 대응한다. `new_pose`/`new_mood`는 프롬프트에 변형 지시문을 추가하고, `idempotencyKey`를 명시하지 않아도 자동으로 새 Job이 된다(동일 사진+장소+비율이라도 `same`과는 다른 요청으로 취급). "다른 배경 선택" 옵션은 이 필드가 아니라 `onePickPlaceId`/`background`를 바꿔 재요청하면 된다 |
| `background` | **사실상 필수** | 배경 이미지 파일. 백엔드가 `Place.thumbnailUrl`/`PlaceImage.imageUrl`(한국관광공사 이미지 URL) 중 **`copyrightCode == "Type1"`인 것만** 가져와 전달한다. `AI_PROVIDER=mock`일 때만 생략 가능(플레이스홀더로 대체) — `gemini` 등 실 프로바이더에서 생략하면 `400 BACKGROUND_REQUIRED` |
| `placeName` | 아니오 | `Place.name`. 프롬프트에 장소명으로 주입된다 |
| `placeRegion` | 아니오 | `Place.region`. 없으면 장면 묘사에 활용 |
| `placeDescription` | 아니오 | `Place.description`. 있으면 장면 묘사로 그대로 쓰인다 — 보낼 수 있으면 보내는 것을 권장 |
| `idempotencyKey` | 아니오 | 백엔드가 재시도를 구분하고 싶을 때 명시적으로 지정. 없으면 (사진 해시 + 장소 + 비율)로 자동 생성되어 동일 요청은 같은 Job을 재사용한다 |
| `sessionId` | 아니오 | 세션/사용자 단위 rate limit에 사용. 없으면 호출자 IP로 대체 |

`placeName`/`placeRegion`/`placeDescription`은 백엔드 `Place` 테이블에 이미 있는 값을
그대로 넘기면 된다 — 별도 조회나 가공이 필요 없다 (`PlaceDetailResponse`가 반환하는
필드와 동일).

**성공 응답 — `202 Accepted`**

```json
{
  "providerJobId": "3f9a...e21",
  "status": "QUEUED",
  "coarseStatus": "RUNNING",
  "stage": "요청 접수",
  "progress": 0,
  "result": null,
  "safety": { "status": "UNKNOWN", "reasonCode": null },
  "error": null,
  "metadata": {
    "provider": "gemini",
    "model": "gemini-3.1-flash-image",
    "promptVersion": "v5",
    "onePickPlaceId": "9c1d4f2e-58a1-4b3a-9d2e-1f6a2b7c9d10",
    "createdAt": "2026-08-08T12:00:00+00:00",
    "completedAt": null,
    "durationMs": null,
    "styleTags": [],
    "estimatedCostUsd": 0.067,
    "attempts": 0
  }
}
```

`estimatedCostUsd`는 요청 접수 시점(202 응답)부터 모델 기준 근사 단가로 채워진다(검토 총평
§2-7) — 정확한 정산이 아니라 단위경제성 추적용 근사치다. `AI_PROVIDER=mock`이면 `0.0`.
합성이 끝나면 공급자가 실제로 돌려준 값으로 다시 채워진다(보통 같은 값).

`promptVersion`이 `v5`(2026-08-31~)다. **API 필드는 바뀌지 않는다** — 프론트·백엔드가
고칠 것은 없고, 달라지는 것은 결과물의 성격과 거부 사유의 종류다.

- v3~v4: 포즈·표정을 장면에 맞게 재조정하고, 조명을 배경 사진에서 직접 읽어 맞춘다.
- v5: 인체 비율(7~7.5등신, 다리는 키의 절반)과 배경과의 스케일 정합을 수치로 강제하고,
  얼굴 보존을 최우선 규칙으로 올렸다. 의상은 장면 유형별 지침
  (`assets/places/outfit_guides.json`)을 따라 원본 옷을 유지한다.

품질 검사도 함께 올라가서, **업로드한 인물 사진과 원본 배경을 검사기에 함께 넘겨**
얼굴이 같은 사람인지·신체 비율이 사람의 것인지·배경이 보존됐는지를 대조한다. 그 결과
`FACE_NOT_PRESERVED`, `PROPORTION_ERROR`, `SCENE_SCALE_BROKEN` 세 가지 거부 사유가
새로 나올 수 있다 (아래 "안전성 거부 사유" 표). 상세는 `docs/PROMPTS.md` 참고.

**오류 응답** — 아래 오류 코드 표 참고. 사진 유효성 검사(B3/B4)에 걸리면 Job을 만들지 않고
바로 4xx를 반환하므로, 백엔드는 이 시점의 오류를 사용자에게 "재업로드 방법 안내"로 그대로
전달하면 된다.

### `GET /v1/generations/{providerJobId}`

Job 상태 조회. 응답 스키마는 위와 동일하되 `DONE`일 때 `result`가 채워진다.

```json
{
  "providerJobId": "3f9a...e21",
  "status": "DONE",
  "coarseStatus": "DONE",
  "stage": "완료",
  "progress": 100,
  "result": {
    "imageReference": "/v1/generations/3f9a...e21/result",
    "width": 1024,
    "height": 1280,
    "aspectRatio": "4:5"
  },
  "safety": { "status": "PASSED", "reasonCode": null },
  "error": null,
  "metadata": {
    "provider": "gemini",
    "model": "gemini-3.1-flash-image",
    "promptVersion": "v5",
    "onePickPlaceId": "9c1d4f2e-58a1-4b3a-9d2e-1f6a2b7c9d10",
    "createdAt": "2026-08-08T12:00:00+00:00",
    "completedAt": "2026-08-08T12:00:24+00:00",
    "durationMs": 24218,
    "styleTags": [{ "category": "mood", "value": "감성적", "confidence": 0.8 }],
    "estimatedCostUsd": 0.067,
    "attempts": 1
  }
}
```

`imageReference`는 절대 URL이 아니라 이 서비스 기준 상대 경로다. 백엔드가 자신의
`AI_BASE_URL`과 조합해 호출한다.

### `GET /v1/generations/{providerJobId}/result`

결과 이미지 바이트. `Content-Type: image/png`, `Content-Disposition: attachment`.
`DONE` 이전이면 `409 JOB_NOT_READY`, TTL 만료 후면 `410 RESULT_EXPIRED`를 반환한다.
백엔드는 이 응답을 그대로 자신의 `TemporaryImageStorage`에 저장하면 된다
(`10_IMAGE_STORAGE.md`의 다운로드 전략과 동일).

### `POST /v1/generations/{providerJobId}/cancel`

`AiGenerationClient.cancel()`에 대응. 이미 종료된(`DONE`/`FAILED`) Job에 호출해도 오류 없이
현재 상태를 반환한다 (멱등).

### `GET /health`

인증 불필요. `{"status": "ok", "jobStore": "redis"|"memory", "provider": "gemini"|"mock"}`.

### `GET /v1/meta`

현재 provider/model/promptVersion, 지원 비율, 업로드 상한, 그리고 **오류 코드와 안전성
거부 사유의 전체 카탈로그**를 반환한다. 뒤의 두 목록은 프론트·백엔드가 화면 문구와
재시도 정책을 자기 쪽에 다시 하드코딩하지 않기 위한 것이다 — 부팅 시 한 번 읽어
캐시하면 된다.

```json
{
  "provider": "gemini",
  "imageModel": "gemini-3.1-flash-image",
  "visionModel": "gemini-3.1-flash-lite",
  "promptVersion": "v5",
  "supportedAspectRatios": ["1:1", "4:5", "9:16"],
  "maxUploadBytes": 10485760,
  "resultTtlSeconds": 86400,
  "errorCodes": [
    { "code": "PROVIDER_TIMEOUT", "httpStatus": 504, "retryable": true,
      "message": "AI 생성이 시간 내에 끝나지 않았습니다." }
  ],
  "safetyReasonCodes": [
    { "code": "FACE_NOT_PRESERVED",
      "message": "결과의 얼굴이 업로드한 사진의 인물과 달라 제공할 수 없습니다." }
  ]
}
```

`errorCodes`는 아래 "오류 코드와 재시도 정책" 표와 같은 내용이고, `safetyReasonCodes`는
`safety.reasonCode`로 실제로 나갈 수 있는 값 전부다. **표를 사람이 읽고 옮겨 적는 대신
이 응답을 쓰는 편이 안전하다** — 표는 갱신을 잊을 수 있지만 이 응답은 코드에서 직접 나온다.

## OpenAPI 스펙

전체 스펙이 [`docs/openapi.json`](./openapi.json)에 커밋돼 있다. 서버를 띄우지 않고도
클라이언트를 생성할 수 있다.

```bash
# 스펙 갱신 (엔드포인트나 스키마를 바꾼 뒤)
python scripts/export_openapi.py

# 코드와 일치하는지 확인만 (CI)
python scripts/export_openapi.py --check
```

`tests/test_api_e2e.py::test_committed_openapi_spec_matches_the_code`가 같은 검사를 하므로,
스펙을 바꾸고 파일 갱신을 잊으면 테스트가 깨진다. 서버를 띄운 상태에서는
`/docs`(Swagger UI)와 `/openapi.json`도 그대로 쓸 수 있다.

## 오류 코드와 재시도 정책

`09_AI_INTEGRATION.md`의 규칙을 그대로 코드화했다.

- timeout / 일시적 공급자 실패 → 제한된 재시도
- 안전성 거부 → 자동 무한 재시도 금지
- 잘못된 사용자 입력 → 재시도 금지

모든 오류 응답은 다음 형태이며, `retryable`을 보고 백엔드가 재시도 여부를 판단한다
(별도 판단 로직 불필요).

```json
{ "error": { "code": "IMAGE_TOO_BLURRY", "message": "사진이 흐려 합성에 사용할 수 없습니다.", "retryable": false } }
```

| code | HTTP | retryable | 발생 시점 / 대응 요구사항 |
|---|---|---|---|
| `INVALID_IMAGE_FORMAT` | 400 | false | 형식 불량/손상/애니메이션 (B1, B3) |
| `IMAGE_TOO_LARGE` | 413 | false | 10MB 초과 (B1) |
| `IMAGE_TOO_MANY_PIXELS` | 413 | false | 압축 폭탄 방지 |
| `NO_PERSON_DETECTED` | 422 | false | 인물 미검출 (B3, B4) |
| `MULTIPLE_PERSONS` | 422 | false | 인물 2명 이상이고 주 피사체를 자동으로 분리할 수 없음 (B3) — 아래 참고 |
| `IMAGE_TOO_BLURRY` | 422 | false | 얼굴 흐림 (B4) |
| `FACE_OCCLUDED` | 422 | false | 얼굴 가림 (B4) |
| `SAFETY_REJECTED_INPUT` | 422 | **false** | 입력 안전성 거부 (E5) |
| `SAFETY_REJECTED_OUTPUT` | 422 | **false** | 출력 안전성·품질 거부 (E5) |
| `PROVIDER_TIMEOUT` | 504 | true | 공급자 타임아웃 (E8) |
| `PROVIDER_ERROR` | 502 | true | 공급자 오류 (E8) |
| `RATE_LIMITED` | 429 | true | 세션/IP 시간당 한도 초과 |
| `BUDGET_EXCEEDED` | 429 | false | 일별 생성 예산 소진 |
| `INVALID_REQUEST` | 400 | false | 필수 필드 누락 등 |
| `BACKGROUND_REQUIRED` | 400 | false | 실 프로바이더인데 `background`도 없고 로컬 카탈로그에도 없음 — 백엔드가 `Place` 이미지를 forwarding해야 함 |
| `UNAUTHORIZED` | 401 | false | `X-API-Key` 누락/불일치 |
| `JOB_NOT_FOUND` | 404 | false | 존재하지 않는 `providerJobId` |
| `JOB_NOT_READY` | 409 | false | 완료 전 결과 다운로드 시도 |
| `RESULT_EXPIRED` | 410 | false | TTL 경과 후 결과 다운로드 시도 |
| `INTERNAL_ERROR` | 500 | true | 예상치 못한 서버 오류 |

### 안전성 거부 사유 (`safety.reasonCode`)

`SAFETY_REJECTED_OUTPUT`으로 실패한 Job은 `safety.reasonCode`에 아래 값 중 하나를 싣는다.
`error.message`에도 같은 뜻의 한국어 문구가 들어가므로 그대로 노출해도 되지만, 화면마다
다른 안내를 하고 싶으면 이 코드로 분기한다. 전체 목록은 `GET /v1/meta`의
`safetyReasonCodes`로도 받을 수 있다.

| reasonCode | 뜻 |
|---|---|
| `HARMFUL_CONTENT` | 결과에 부적절한 내용이 포함됨 |
| `FACE_DISTORTED` | 얼굴이 뭉개지거나 부자연스럽게 생성됨 |
| `PROPORTION_ERROR` | 신체 비율이 사람의 것이 아님 (등신·다리 길이) |
| `ANATOMY_ERROR` | 손발 개수·관절 등 신체 오류, 하체 소실 |
| `SCENE_SCALE_BROKEN` | 인물과 배경의 크기·원근 불일치 |
| `BACKGROUND_ALTERED` | 배경 관광지 사진이 원본과 다르게 변형됨 (간판 글자 등) |
| `PERSON_COUNT_MISMATCH` | 합성된 인물 수가 1이 아님 |
| `SEVERE_ARTIFACTS` | 결과 품질이 기준 미달 |
| `PROVIDER_BLOCKED` | 공급자 자체 안전 필터가 차단 |

### 경고 — 결과는 주되 알려야 하는 것 (`safety.warnings`)

**`FACE_NOT_PRESERVED`는 더 이상 Job을 실패시키지 않는다.** 얼굴이 화면에서 작게 찍힌
사진은 흔한 여행 사진이라, 그걸 이유로 결과를 못 받게 하면 정상 사용자가 대량으로
막힌다. 대신 결과를 그대로 주고 `safety.warnings`에 실어 보낸다.

```json
{
  "status": "DONE",
  "safety": {
    "status": "PASSED",
    "reasonCode": null,
    "warnings": [
      { "code": "FACE_NOT_PRESERVED",
        "message": "얼굴이 실제 모습과 조금 다르게 표현됐을 수 있습니다. 마음에 들지 않으면 다시 만들어 보세요." }
    ]
  }
}
```

- `warnings`는 **선택 필드**다. 무시해도 기존 연동은 그대로 동작한다.
- 경고가 있어도 `status`는 `PASSED`, Job은 `DONE`이고 결과 이미지가 나온다.
  `reasonCode`는 `null`이다 — 여기 값이 있으면 실패로 오인되기 때문이다.
- 어떤 코드가 경고이고 어떤 코드가 거부인지는 `GET /v1/meta`의 `safetyReasonCodes[].severity`
  (`warn` | `reject`)로 알 수 있다.
- **프론트 권장**: 경고를 노출하고 다시 만들기 버튼을 함께 보여준다.

서버는 이 경고를 내기 전에 이미 최대 `faceRegenerateMaxAttempts`(`GET /v1/meta`, 기본 3)
번까지 다시 합성해 본다. 그래서 한 Job이 평균 45초 안팎, 최악의 경우 그보다 길어질 수
있으니 **백엔드 폴링 타임아웃을 이 값에 맞춰 잡아야 한다.**

## 개인정보 처리

- 사용자 원본 사진은 Job이 끝나는 즉시(성공/실패 무관) 서버에서 삭제한다.
- 결과 이미지는 `RESULT_TTL_SECONDS`(기본 24시간) 후 정리 루프가 삭제한다.
- 로그에는 이미지 바이트, 원본 파일명, 얼굴 데이터를 남기지 않는다.
- 백엔드는 이 서비스에서 받은 결과를 저장한 뒤 **가능한 한 빨리 자신의 TTL 정책에 맞춰
  다운로드를 완료**해야 한다. 이 서비스가 결과를 영구 보관하지 않기 때문이다.

## 로컬 통합 테스트

Gemini 키 없이도(`AI_PROVIDER=mock`) 전체 왕복을 확인할 수 있다. mock 모드에서는
`background`를 생략해도 플레이스홀더로 대체되므로 `onePickPlaceId`에 아무 문자열이나
넣어도 된다 (실제 `Place.id`일 필요 없음).

```bash
docker compose up --build

curl -H "X-API-Key: $AI_API_KEY" \
     -F photo=@tests/fixtures/person.jpg \
     -F onePickPlaceId=9c1d4f2e-58a1-4b3a-9d2e-1f6a2b7c9d10 \
     -F aspectRatio=4:5 \
     http://localhost:8100/v1/generations

curl -H "X-API-Key: $AI_API_KEY" http://localhost:8100/v1/generations/{id}
curl -H "X-API-Key: $AI_API_KEY" http://localhost:8100/v1/generations/{id}/result -o out.png
```

실 프로바이더(`AI_PROVIDER=gemini`)를 로컬에서 테스트할 때는 `background`를 반드시
함께 보내야 한다 (없으면 `BACKGROUND_REQUIRED`).

```bash
curl -H "X-API-Key: $AI_API_KEY" \
     -F photo=@tests/fixtures/person.jpg \
     -F background=@tests/fixtures/anmok-beach.jpg \
     -F onePickPlaceId=9c1d4f2e-58a1-4b3a-9d2e-1f6a2b7c9d10 \
     -F placeName=안목해변 \
     -F placeDescription="동해 바다와 백사장이 펼쳐진 해변" \
     -F aspectRatio=4:5 \
     http://localhost:8100/v1/generations
```

"구도, 스타일만 살짝 조정" 재생성(E4)을 테스트할 때는 `variationMode`를 함께 보낸다 —
`idempotencyKey` 없이도 원본 요청과 자동으로 다른 Job이 된다.

```bash
curl -H "X-API-Key: $AI_API_KEY" \
     -F photo=@tests/fixtures/person.jpg \
     -F onePickPlaceId=9c1d4f2e-58a1-4b3a-9d2e-1f6a2b7c9d10 \
     -F aspectRatio=4:5 \
     -F variationMode=new_pose \
     http://localhost:8100/v1/generations
```

백엔드 로컬 실행 시 `.env`에 다음을 설정한다.

```
AI_BASE_URL=http://localhost:8100
AI_API_KEY=<이 서비스의 AI_API_KEY와 동일한 값>
```
