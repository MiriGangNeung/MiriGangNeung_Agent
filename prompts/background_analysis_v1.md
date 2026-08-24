---
version: v1
purpose: 배경 이미지 실시간 분석 (프롬프트 생성 시 scene/lighting 힌트 확보)
inputs: [background_image]
output: JSON
---

Analyze the attached background photo of a real-world outdoor or indoor location
that will be used as a photo-composition backdrop.

Answer strictly as JSON, with no prose and no markdown fence:

```
{
  "scene_description": "1-2 sentences describing the setting (in Korean)",
  "lighting": "time of day, weather, light direction/quality (in Korean)",
  "notable_features": ["눈에 띄는 지형지물/사물 1", "..."],
  "mood_tags": ["분위기 태그 1", "..."]
}
```

Rules:

- `scene_description`: what the place looks like — terrain, structures, water,
  vegetation, crowd level. 1-2 short Korean sentences.
- `lighting`: time-of-day and light quality (예: "맑은 날 오후, 부드러운 측광",
  "노을, 따뜻한 색감").
- `notable_features`: distinctive landmarks or objects visible in the frame, at
  most 5 short Korean phrases.
- `mood_tags`: overall atmosphere, at most 5 short Korean phrases (예: "여유로움",
  "이국적", "고요함").
- Describe only the location itself. Do not describe or infer anything about
  any person who might appear in the frame.
- If the image is unclear or not a real-world location, return empty strings/
  arrays rather than guessing.
