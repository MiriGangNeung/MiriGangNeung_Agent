# ADR-0003: 장소 특징 VLM 사전 분석 파이프라인

- 상태: 승인됨
- 날짜: 2026-08-24

## 배경

`resolve_place_context()`(`app/places/backgrounds.py`)는 합성 프롬프트의 장면
(`scene_hint`)·조명(`lighting_hint`) 힌트를 지금까지 백엔드가 보내는
`placeDescription` 같은 짧은 텍스트 필드에만 의존해 만들었다. 촬영 시간대, 지배적
색감, 눈에 띄는 지형지물, 프레이밍처럼 배경 일치도를 높이는 데 실제로 도움이 되는
정보는 빠져 있었다.

백엔드를 다시 조사한 결과 두 가지가 확인됐다.

1. 각 `Place`는 이제 Tour API의 `detailImage2` 갤러리 호출로 채워지는 여러 장(개수
   미확정, 상한 없음)의 `PlaceImage`를 갖는다 (`GET /api/v1/places/{id}` →
   `images[]`, `PlaceImageResponse{imageUrl, title, source, sortOrder,
   copyrightCode}`).
2. 각 이미지에는 Tour API 원본 `cpyrhtDivCd` 필드가 `copyrightCode`로 그대로
   내려온다. 공식 매뉴얼(`api_manual_guide/markdown/1. ...v4.4.md`)에 따르면 실제
   값은 두 가지뿐이다 — `Type1`(제1유형, 출처표시만 하면 됨, **변경 허용**) /
   `Type3`(제1유형 + **변경금지**). AI 합성은 원본을 변형하는 행위이므로 `Type3`
   이미지는 합성 배경으로 쓸 수 없다. 현재 백엔드 어디에도 이 필드로 걸러내는 로직이
   없다 (`PlaceService.upsert()` 등은 URL 존재 여부만 검사).

## 결정

**오프라인 배치 스크립트로 상위 10개 장소를 VLM 사전 분석해 커밋된 리포트로
저장하고, 요청 처리 경로는 그 리포트를 읽기만 한다.**

- 대상 장소 선정: 백엔드 `GET /api/v1/places` + `GET /api/v1/places/{id}`로
  `copyrightCode == "Type1"` 이미지만 필터링한 뒤, Type1 이미지 개수가 많은 순으로
  상위 N개(기본 10)를 고른다. 이미지가 많다는 것은 그만큼 자주 촬영된, 신뢰도 높은
  "인생샷 후보" 장소라는 신호이기도 하다. 장소당 분석 이미지는 5장으로 상한을 둔다.
- 분석 모델: **Hugging Face Inference Providers의 무료 크레딧**으로 호출하는
  비전 지원 채팅 모델(`huggingface_hub.InferenceClient.chat_completion`). 10개
  장소 × 이미지 몇 장 수준의 저빈도 배치 작업에 유료 Gemini를 쓸 이유가 없다.
- **로컬 VLM 실행은 하지 않는다.** 이 개발 환경은 RAM 7.5GB(가용 약 5.8GB), GPU
  없음(WSL2, `nvidia-smi` 미탐지)이다. 7B급 비전-언어 모델은 CPU-only 환경에서
  fp16 기준 14GB+, 4bit 양자화해도 5~6GB를 거의 다 써서 실행이 사실상 불가능하거나
  이미지 1장에 수 분이 걸린다. 원격 호스팅 Inference API를 쓰면 이 제약과
  무관해진다. **혹시 특정 모델이 무료 호스팅 목록에서 빠져 로컬 실행으로 폴백해야
  하면, BLIP-base류(~1GB) 같은 경량 캡셔닝 모델로만 제한한다** — 이 환경에서
  실행 가능한 상한선이다.
- 결과 저장: `assets/places/place_insights.json` (커밋되는 산출물, 지금의
  `assets/backgrounds/backgrounds.json`과 동일한 취급). 재실행은 수동/주기적으로
  하며, 이번 범위에서 자동 스케줄링은 만들지 않는다.
- 런타임 통합: `resolve_place_context()`의 우선순위에 한 단계 추가
  (개발 카탈로그 → **place_insights.json 매칭** → 백엔드 제공 필드 → 범용 문구).
  `place_insights.json`이 없거나 비어 있어도, 또는 특정 `Place.id`가 상위 10개에
  들지 못해도 서비스는 기존 방식으로 정상 동작한다 — 배치 결과에 런타임이 강하게
  의존하지 않는다.
- 의존성 배치: `huggingface_hub`는 배치 스크립트 전용이라 `requirements-dev.txt`에만
  넣는다. 배포되는 Docker 이미지(`requirements.txt` 기준)에는 영향이 없다.

## 검토한 대안

1. **요청 처리 경로에서 매번 VLM 호출.** 기각 — 무료 서버리스 추론은 콜드
   스타트·속도 제한이 흔해 사용자 요청 지연 시간(P95 목표)에 영향을 준다. 이미
   Gemini vision을 스타일 분석/품질 검사에 쓰고 있는데, 장소 배경 설명까지 매번
   다시 분석할 이유도 없다 — 같은 장소는 사진이 자주 바뀌지 않는다.
2. **로컬에서 VLM을 직접 서빙.** 기각 — 위에서 설명한 RAM/GPU 제약.
3. **전체 장소를 다 분석.** 기각 — Type3 라이선스 이미지가 섞여 있고, 장소 수가
   많아질수록 무료 크레딧 소진 속도도 빨라진다. 우선 상위 10개로 범위를 좁히고,
   필요하면 `--top-n`으로 나중에 늘린다.

## 결과

- `app/places/insights.py`(런타임 로더), `scripts/analyze_top_places.py`(배치
  CLI), `assets/places/place_insights.json`(산출물) 신규 추가.
- `app/places/backgrounds.py::resolve_place_context()` 우선순위 확장.
- `Type1`/`Type3` 구분은 이번에 처음 코드로 반영됐다 — 백엔드 쪽에도
  `docs/AI_API_CONTRACT.md`를 통해 "Type1만 forwarding 가능"을 전달해야 한다.
- Type1이어도 "출처표시-권장"이므로, 최종 합성 이미지 또는 그 주변 UI에 한국관광공사
  출처 표기가 필요하다 — 이건 백엔드/프론트 팀 몫이며 이번 변경 범위 밖이다.
