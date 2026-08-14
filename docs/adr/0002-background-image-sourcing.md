# ADR-0002: 배경 이미지는 어디서 오는가

- 상태: 승인됨
- 날짜: 2026-08-09

## 배경

ADR-0001에서 사진 전송 방식을 multipart로 정하면서 `background`를 선택 필드로 만들고,
없을 때 쓸 로컬 배경 카탈로그(`assets/backgrounds/backgrounds.json`)를 함께 만들었다.
이후 백엔드 리포(`MiriGangNeung_BackEnd`)의 `Place`/`PlaceImage` 도메인, `PlaceService`,
`KoreanTourApiClient`, `07_DATA_MODEL.md`를 다시 확인한 결과 두 가지 문제가 드러났다.

1. **ID 불일치.** `07_DATA_MODEL.md`에 따르면 `CompositionJob.onePickPlaceId`는 `Place`
   테이블을 가리키는 FK이며, `Place.id`는 UUID다. 그런데 로컬 카탈로그는
   `anmok-beach` 같은 임의 슬러그를 키로 썼다 — 운영에서 백엔드가 보내는 실제
   `onePickPlaceId`(UUID)와는 절대 매칭되지 않는다.
2. **소유권 오해.** 백엔드는 관광지 이미지를 파일로 갖고 있지 않다. `Place.thumbnailUrl`,
   `PlaceImage.imageUrl`은 한국관광공사가 직접 호스팅하는 원격 URL 문자열일 뿐이다
   (`PlaceService.upsert()`가 Tour API 응답의 `firstimage` 필드를 그대로 저장). 즉
   "이 서비스가 관광지 사진을 로컬에 갖고 있어야 한다"는 전제 자체가 틀렸다.

로컬 카탈로그의 `usable: true` + `license: "TBD"` 조합도 자체 모순이었다 (요구사항 C3:
사용 권한 불명확한 이미지는 배경에서 제외해야 한다).

## 검토한 대안

1. **이 서비스가 Tour API를 직접 호출한다.** 기각 — 백엔드 문서(C1/C2, `11_EXTERNAL_APIS.md`)가
   외부 관광 데이터 수집·정규화를 명시적으로 백엔드 책임으로 두고 있다. 같은 통합을
   두 서비스에 중복 구현하면 `TOUR_API_KEY`도 이중 관리해야 하고, 캐싱·장애 대응
   전략이 두 곳에서 어긋날 위험이 있다.
2. **이 서비스가 `backgroundImageUrl`을 받아 직접 fetch한다.** 기각 — 외부(정확히는
   한국관광공사 CDN)에서 온 임의 URL을 서버가 fetch하는 구조라 SSRF 방어(허용
   도메인 검증 등)가 새로 필요하고, 백엔드가 이미 Place 조회 시점에 그 바이트를
   확보할 수 있는데 굳이 이 서비스가 다시 네트워크 왕복을 하게 된다.
3. **백엔드가 이미지 바이트를 가져와 multipart로 전달한다.** 채택.

## 결정

- `background`는 **`AI_PROVIDER=mock`이 아닌 한 사실상 필수**다. 백엔드가
  `Place.thumbnailUrl` 또는 `PlaceImage.imageUrl`에서 이미지 바이트를 가져와
  `POST /v1/generations`의 `background` 파일 필드로 함께 보낸다.
- `background`도 `placeName`/`placeRegion`/`placeDescription`도 없이 실 프로바이더로
  요청이 오면 조용히 플레이스홀더를 합성하는 대신 `400 BACKGROUND_REQUIRED`로
  명확히 실패한다 (`app/api/routes_generation.py::_resolve_background`). 사용자에게
  가짜 그라디언트 배경의 "인생샷"을 내보내는 것보다, 통합이 안 됐다는 사실을
  드러내는 편이 낫다.
- `placeName`/`placeRegion`/`placeDescription`을 새 선택 필드로 추가했다. 백엔드가
  이미 `Place` 테이블에 갖고 있는 값이라 추가 조회 없이 그대로 넘기면 되고,
  프롬프트의 장소 설명 품질을 카탈로그보다 훨씬 정확하게 만든다
  (`app/places/backgrounds.py::resolve_place_context`).
- 로컬 배경 카탈로그(`assets/backgrounds/backgrounds.json`)는 **`AI_PROVIDER=mock` 로컬
  개발·curl 수동 테스트 전용**으로 용도를 명확히 하고, 모든 항목을 `usable: false`로
  고정했다 (라이선스 미확인 상태를 그대로 반영). 관련 함수도 `get_dev_place`,
  `load_dev_background_image`로 이름을 바꿔 "이건 운영 데이터가 아니다"를 코드 레벨에서
  드러냈다.

## 결과

- 백엔드 `HttpAiGenerationClient` 구현 범위에 "Place 이미지 URL에서 바이트를 가져와
  forwarding"이 새로 추가됐다 (`docs/AI_API_CONTRACT.md` 변경 5번).
- 실 프로바이더 요청 시 배경 누락을 Job 생성 전에 동기로 잡아낸다 — 사진 검증(B3/B4)과
  동일한 "빨리 실패" 원칙.
- 관광지 사진의 저작권 확인·관리는 여전히 전적으로 백엔드(C3)의 책임으로 남는다.
  이 서비스는 그 결과물(바이트)만 소비한다.
