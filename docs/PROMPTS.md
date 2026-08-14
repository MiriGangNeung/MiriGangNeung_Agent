# 프롬프트 버전 이력

프롬프트 본문은 `prompts/*.md`에 있다. 이 파일은 무엇이 왜 바뀌었는지의 요약이다.
버전을 올릴 때는 기존 파일을 수정하지 말고 새 파일을 추가한 뒤
`app/pipeline/prompt.py`의 `PROMPT_VERSION`을 올린다. `promptVersion`은 백엔드가
생성 이력(E9)에 기록하는 값이므로, 프롬프트가 바뀌었는데 버전이 그대로면 과거
생성물과 구분이 안 된다.

## v1 (2026-08-09)

- `composition_v1.md` — 인물+배경 합성. 얼굴/의상/체형 동일성 보존을 최우선으로
  명시하고, 조명·그림자·원근 일치를 요구. 배경 카탈로그의 `sceneHint`/`lightingHint`와
  B6 스타일 태그(신뢰도 0.4 이상만)를 주입한다.
- `quality_check_v1.md` — 출력 안전성·품질 판정. `person_count`, `face_natural`,
  `anatomy_correct`, `harmful_content`, `severe_artifacts`를 JSON으로 강제.
- `style_analysis_v1.md` — 의상/색상/무드/포즈/배경 적합도를 카테고리당 1개씩,
  한국어 짧은 문구 + 신뢰도로 추출.

초기 버전이라 이전 버전과의 비교 대상 없음.
