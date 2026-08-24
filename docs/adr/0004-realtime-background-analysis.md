# ADR-0004: 실시간 배경 이미지 분석 (오프라인 캐시 미스 폴백)

- 상태: 승인됨
- 날짜: 2026-08-24

## 배경

ADR-0003은 "백엔드가 여러 후보를 넘기면 그중 사진이 많은 상위 10개 장소를 오프라인
VLM으로 사전 분석해 `place_insights.json`에 캐시해 두고, 요청 처리 경로는 그
캐시를 `Place.id`(UUID)로 조회만 한다"는 설계였다. 이 설계는 "후보 소스가
`GET /api/v1/places/{id}` → `images[]`(Tour API `detailImage2` 갤러리, `Place`에
종속)"라는 전제 위에 있었다.

`MiriGangNeung_BackEnd` 원격 저장소를 다시 조사한 결과 이 전제가 실제와 다르다는
것을 확인했다. 백엔드에는 배경 후보를 제공하는 경로가 **셋**이다.

1. `GET /api/v1/places/{id}` → `images[]` — ADR-0003이 대상으로 삼은 경로.
   `Place.id` UUID에 종속, `copyrightCode` 있음.
2. `GET /api/v1/award-photos` (`AwardPhotoService`, KTO 관광공모전 수상작
   `PhokoAwrdService/phokoAwrdSyncList`) — `copyrightCode` 있음, id는
   `kto-award:<contentId>` (프론트 어댑터가 붙이는 표시용 식별자).
3. `GET /api/v1/tourism-photos` (`TourismPhotoService`, KTO 관광사진갤러리
   `PhotoGalleryService1/galleryList1`) — **응답 DTO(`TourismPhotoResponse`)에
   `copyrightCode` 필드 자체가 없다.** id는 `kto-gallery:<galContentId>`.

백엔드 설계 문서(`docs/superpowers/specs/2026-08-10-tour-photo-source-tabs-design.md`)
에 따르면, 사용자가 실제로 배경을 고르는 "1번 배경 선택 화면"은 (1)이 아니라
**(2)/(3) 두 탭**으로 구성되고 기본 탭은 `award`다. 같은 문서가 명시적으로 남긴
제한: "두 API의 사진 ID는 배경 선택 화면의 표시용 식별자다. 실제 관광지 `Place`
ID가 아니므로 코스 생성·상세 관광지 API의 장소 식별자로 직접 사용할 수 없다."
공모전 POC 설계서의 "후속 전환 조건" 4번("AI 합성에 수상작을 배경 후보와 구도
참조로 어떻게 전달할지")도 아직 결정되지 않은 채 남아 있다.

즉 사용자가 실제로 고르는 배경의 상당수는 `onePickPlaceId`가 `Place` UUID가
아니어서, ADR-0003의 `place_insights.json`(Place UUID 키)에 애초에 매칭될 수
없다. (1) 경로로 고른 소수의 경우에만 여전히 유효하다.

## 결정

**오프라인 캐시가 미스일 때만, 이번 요청의 실제 배경 이미지 바이트를 실시간
분석해 프롬프트 힌트로 쓴다.**

- 근거 소스가 무엇이든(Place 갤러리든 award-photos든 tourism-photos든) 배경 이미지
  바이트는 `POST /v1/generations`의 `background` 멀티파트 필드로 매 요청마다 이미
  전달된다 (`app/api/routes_generation.py::create_generation` → `_resolve_background`).
  ID 매칭에 의존하지 않고 이 바이트를 직접 분석하는 것이 소스에 관계없이 항상
  동작하는 유일한 방법이다.
- `app/providers/base.py::ImageCompositionProvider.analyze_background()` 추상
  메서드 추가. `GeminiProvider`는 이미 스타일 분석(B6)·품질 검사(E5)에 쓰는 것과
  같은 `vision_model`/`_ask_json()` 경로를 재사용한다 — 새 비용 등급이 아니다.
- `app/jobs/runner.py::_execute()`가 `app/places/backgrounds.py::
  has_precomputed_place_context()`로 1·2순위(개발 카탈로그, `place_insights.json`)
  매치 여부를 먼저 확인하고, **미스일 때만** `provider.analyze_background()`를
  호출한다. 분석 실패(타임아웃/파싱 오류)는 로그만 남기고 `None`으로 폴백한다 —
  이 단계 실패가 Job 전체를 실패시키지 않는다.
- `resolve_place_context()`의 우선순위가 4단계에서 5단계로 늘었다: 개발 카탈로그
  → `place_insights.json` → **실시간 분석** → 백엔드 텍스트 필드 → 범용 문구.

### ADR-0003의 대안 검토와의 관계

ADR-0003은 "요청 처리 경로에서 매번 VLM 호출"을 대안으로 검토하고 지연시간을
이유로 기각했다. 이 결정은 여전히 유효하다 — 이번 결정은 그것을 뒤집는 것이
아니라, **오프라인 캐시가 커버하지 못하는 나머지(award-photos/tourism-photos
등, 실제로는 다수일 것으로 예상)에 대해서만** 실시간 분석을 폴백으로 추가하는
것이다. 캐시가 히트하는 소수의 인기 장소는 여전히 추가 호출 없이 즉시 응답한다.

## 검토한 대안

1. **`place_insights.json` 생성 대상을 award-photos/tourism-photos까지 확장.**
   기각 — 두 소스는 `Place`에 묶여 있지 않고 백엔드 자체도 이 사진들을 DB에
   저장하지 않는다(공모전 POC 설계서: "사진 데이터를 DB에 저장하거나
   `places`/`place_images`에 동기화하지 않는다"). 어떤 안정적인 키로 오프라인
   캐시를 미리 만들어 둘 수 있는 근거가 없다 — award-photos는 전국 약 95건이라도
   `region`/키워드 파라미터에 따라 응답이 바뀔 수 있고, tourism-photos는 아예
   저작권 필드가 없어 Type1 필터링조차 오프라인에서 할 수 없다.
2. **캐시 미스 시 백엔드 텍스트 필드로만 폴백(현행 유지, 아무것도 추가하지
   않음).** 기각 — 조사 결과 이 경로가 오히려 다수가 될 가능성이 높아, ADR-0003이
   해결하려던 "일반적인 문장 수준 프롬프트" 문제가 대부분의 실제 요청에서
   그대로 남는다.
3. **모든 요청에 대해 무조건 실시간 분석.** 기각 — 캐시가 히트하는 경우까지
   불필요한 vision 호출을 추가하면 비용·지연시간만 늘어난다. 캐시 우선 + 미스
   폴백이 정확도와 비용의 균형점이다.

## 결과

- `app/providers/base.py`에 `BackgroundAnalysis`, `analyze_background()` 추가
  (모든 `ImageCompositionProvider` 구현체와 테스트 더블에 영향).
- `prompts/background_analysis_v1.md` 신규.
- `app/places/backgrounds.py::has_precomputed_place_context()` 신규,
  `resolve_place_context()`에 3순위 추가.
- `app/jobs/runner.py`가 캐시 미스를 판단해 조건부로 `analyze_background()`를
  호출.
- 백엔드 쪽에 남은 계약상 공백 — `docs/AI_API_CONTRACT.md`에 각주로 남김:
  (a) award-photos/tourism-photos에서 고른 배경은 `onePickPlaceId`가 실제
  `Place` UUID가 아닐 수 있다. (b) `tourism-photos` 응답에는 `copyrightCode`가
  없어 Type1 여부를 백엔드도 판단할 수 없다 — 이 AI 서비스는 `background` 바이트가
  이미 Type1로 필터링돼 왔다고 신뢰할 뿐 스스로 재검증하지 않으므로, 이 공백은
  백엔드 팀이 별도로 해소해야 한다.
