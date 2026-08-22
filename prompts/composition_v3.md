---
version: v3
purpose: 인물 사진 + 강릉 관광지 배경 합성 (요구사항 E1~E4), 인스타그램 감성 톤 + 포즈·표정 자연스러운 변경, 재생성 시 구도·분위기 변형 지원
inputs: [person_image, background_image, place_name, scene_hint, lighting_hint, style_tags, aspect_ratio, variation_mode]
---

You are compositing a travel photo preview for a Korean tourism service. The goal is a
photo the person would actually want to post — not a stiff, literal cut-and-paste.

**Image 1** is a photo of a real person. **Image 2** is a background photograph of a real tourist site in Gangneung, South Korea.

Create a single photorealistic image that places the person from Image 1 naturally into the scene of Image 2.

## Identity preservation (highest priority)

- Keep the person clearly and unmistakably recognizable as the same individual: preserve their face shape, eyes, nose, mouth, skin tone, hairstyle and hair color.
- Preserve their clothing, its colors, patterns and fit.
- Preserve their approximate body proportions and build.
- Do not beautify, slim, age, de-age, or otherwise alter the person's fundamental appearance.
- Do not change their apparent gender, ethnicity, or age.

## Pose and expression

Unlike a passport photo, this should read as a candid travel moment. You may naturally adjust:

- **Pose**: a relaxed, camera-aware travel pose that fits the scene — e.g. a slight body turn, walking, looking out toward the view, hands in pockets — instead of a stiff, straight-on stance.
- **Expression**: a genuine, warm expression that fits a happy travel moment — e.g. a natural smile or soft candid look — instead of a flat, neutral studio expression.

Keep both changes subtle and true to the person's real face and demeanor from Image 1 — this is the same person having a good moment, not a different person.

## Scene integration

- Location: {place_name}
- Scene: {scene_hint}
- Lighting: {lighting_hint}

Match the person to the scene so the result reads as one photograph:

- Relight the person to match the background's light direction, color temperature and intensity.
- Cast a contact shadow on the ground consistent with that light direction.
- Match the background's perspective and horizon line — the person's eye level and scale must be plausible for where they stand.
- Match grain, sharpness, contrast and color grading between subject and background.
- Keep the person fully within frame, posed naturally on a plausible surface.

## Aesthetic direction (Instagram-style travel photo)

- Color grade like a well-shot travel Instagram post: rich, slightly warm skin tones, deep natural blues/greens in sky and water, gentle contrast — not flat, not washed out, not over-filtered.
- Frame it like a considered travel photo rather than a snapshot: favor off-center, rule-of-thirds placement of the person over dead-center symmetry when the scene allows it.
- Keep it tasteful, realistic and true to the actual scene and lighting — this must still read as a real photograph, not an illustration, painting, or heavily stylized filter.

## Photographic style

{style_direction}

## Regeneration variation

{variation_direction}

Output a {aspect_ratio} photograph. Photorealistic. No text, no watermarks, no logos, no borders, no collage.

## Hard constraints

- Exactly one person in the output.
- Anatomically correct: five fingers per visible hand, two arms, two legs, no duplicated or missing limbs.
- No nudity, no suggestive posing, no violence.
- Do not add other recognizable people to the scene.
