---
version: v1
purpose: 인물 사진 + 강릉 관광지 배경 합성 (요구사항 E1~E4)
inputs: [person_image, background_image, place_name, scene_hint, lighting_hint, style_tags, aspect_ratio]
---

You are compositing a travel photo preview for a Korean tourism service.

**Image 1** is a photo of a real person. **Image 2** is a background photograph of a real tourist site in Gangneung, South Korea.

Create a single photorealistic image that places the person from Image 1 naturally into the scene of Image 2.

## Identity preservation (highest priority)

- Preserve the person's facial identity exactly: face shape, eyes, nose, mouth, skin tone, hairstyle and hair color.
- Preserve their clothing, its colors, patterns and fit.
- Preserve their approximate body proportions and build.
- Do not beautify, slim, age, de-age, or otherwise alter the person's appearance.
- Do not change their apparent gender, ethnicity, or age.

## Scene integration

- Location: {place_name}
- Scene: {scene_hint}
- Lighting: {lighting_hint}

Match the person to the scene so the result reads as one photograph:

- Relight the person to match the background's light direction, color temperature and intensity.
- Cast a contact shadow on the ground consistent with that light direction.
- Match the background's perspective and horizon line — the person's eye level and scale must be plausible for where they stand.
- Match grain, sharpness, contrast and color grading between subject and background.
- Keep the person fully within frame, standing or posed naturally on a plausible surface.

## Photographic style

{style_direction}

Output a {aspect_ratio} photograph. Photorealistic. No text, no watermarks, no logos, no borders, no collage.

## Hard constraints

- Exactly one person in the output.
- Anatomically correct: five fingers per visible hand, two arms, two legs, no duplicated or missing limbs.
- No nudity, no suggestive posing, no violence.
- Do not add other recognizable people to the scene.
