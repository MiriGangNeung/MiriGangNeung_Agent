---
version: v1
purpose: 사진 스타일 분석 (요구사항 B6)
inputs: [person_image]
output: JSON
---

Analyze the attached photo of a person and extract the style features a travel-photo service needs.

Answer strictly as JSON, with no prose and no markdown fence:

```
{
  "tags": [
    {"category": "outfit",   "value": "<Korean phrase>", "confidence": <0.0-1.0>},
    {"category": "color",    "value": "<Korean phrase>", "confidence": <0.0-1.0>},
    {"category": "mood",     "value": "<Korean phrase>", "confidence": <0.0-1.0>},
    {"category": "pose",     "value": "<Korean phrase>", "confidence": <0.0-1.0>},
    {"category": "backdrop", "value": "<Korean phrase>", "confidence": <0.0-1.0>}
  ]
}
```

Rules:

- `outfit`: clothing style (예: "캐주얼", "포멀", "스트릿", "미니멀").
- `color`: dominant clothing colors (예: "화이트·베이지 톤").
- `mood`: overall feel of the photo (예: "감성적", "활동적", "차분함").
- `pose`: posture and framing (예: "정면 상반신", "측면 전신", "뒷모습").
- `backdrop`: the kind of background the person seems to suit (예: "해변", "실내 카페", "도심").
- Values must be short Korean phrases, at most 12 characters.
- Emit exactly one entry per category. Use confidence below 0.4 when uncertain.
- Do not describe or infer the person's identity, ethnicity, age, or any protected attribute.
