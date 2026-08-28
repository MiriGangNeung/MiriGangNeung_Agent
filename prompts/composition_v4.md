---
version: v4
purpose: 인물 사진 + 강릉 관광지 배경 합성 (요구사항 E1~E4), 사전 분석된 배경 이미지의
  구조화된 배치/조명/카메라 데이터로 정확한 합성 지시. 구조화 데이터가 없는 경우
  (개발 카탈로그·실시간 분석·백엔드 텍스트 필드 폴백)는 scene_hint/lighting_hint와
  일반적인 기본 문구로 대체된다.
inputs: [person_image, background_image, place_name, scene_hint, lighting_hint, placement,
  lighting, camera, mood_tags, color_palette, style_tags, aspect_ratio, variation_mode]
---

You are given TWO input images:
- [subject image]: an uploaded photo of a real user (the person).
- [background image]: a real tourist-site photo of {place_name} in Gangneung, South Korea, fetched from a URL.

Background: {scene_hint} {lighting_hint}

Task: composite the person from [subject image] into [background image] to
produce ONE natural, photorealistic photograph.

## Background integrity

- Use [background image] as-is. Do NOT alter, redraw, recolor, crop, or restyle
  it. Keep it pixel-consistent; only the added person and their shadow are new.

## Placement

- Put the person at {subject_zone}, standing/sitting on {ground_plane}.
- They must have both feet on a surface a person could really stand on. Never
  place them on water, surf, wet or loose rocks, riprap, or an active roadway —
  even if that is what fills the foreground. If the named surface is not
  clearly visible, move them to the nearest part of the frame where someone
  could plausibly stand, rather than floating them over the foreground.
- Keep {occluding_elements} in front of the person so they are partially
  occluded naturally. If there is nothing to occlude with, place the person
  fully unobstructed.

## Lighting (match person to scene)

- Scene lighting: {time_of_day}, light from {light_direction} at a
  {light_angle} angle, {color_temperature} temperature, {shadow_hardness}
  shadows.
- Relight the person to match this exactly, and cast a correct contact shadow
  at the feet in the same direction as the scene's existing shadows.

## Perspective & scale

- Match the camera: {camera_perspective}, horizon at {horizon_position}.
- Frame the result as {suggested_framing}.
- Keep the person's size and perspective consistent with nearby objects in the
  background.

## Color

- Blend the person's color grading toward the scene mood ({mood_tags}) and
  palette ({color_palette}) so they belong to the same photograph.

## How people are photographed at this specific place

This is field research written by people who know the location. Where it
conflicts with the automated measurements below — subject size, framing, where
to stand — **this section wins**.

{place_pose_direction}

## Pose and expression (repose the subject — do not paste them as-is)

The subject image is usually a stiff, straight-on studio shot. Copying that pose
into a travel scene is exactly what makes a composite look fake. Re-pose the
person so they read as someone actually standing there:

- **Pose**: a relaxed, camera-aware travel pose that suits this specific
  location — a slight body turn, weight on one leg, walking, looking out toward
  the view, hands in pockets. Not a frontal, symmetrical, arms-at-side stance.
- **Expression**: a genuine, warm expression for a good travel moment — a
  natural smile or soft candid look — not a flat studio expression.
- **Interaction with the scene**: the body should relate to the environment —
  facing along the shoreline, leaning toward the view, turned into the light.

This is repose, not replacement: same person, same face, same outfit, having a
good moment.

## Photographic style

{style_direction}

## Regeneration variation

{variation_direction}

## Identity (critical)

- Preserve the person's face, hairstyle, skin tone, build and clothing from
  [subject image]. Do not beautify, age, slim, or change any features.
- Do not change their apparent gender, ethnicity, or age.
- Identity is about *who they are*, not *how they are standing* — changing the
  pose, body angle and expression as directed above is required, not a
  violation of this rule.

## Output

A single seamless {aspect_ratio} photograph. Photorealistic. No collage, no
borders, no text, no watermarks, no logos.

## Negative

altered/blurred/recolored background, floating subject, subject standing on
water/rocks/traffic where a person could not actually stand, cut-out or sticker
edges, stiff frontal studio pose copied from the subject image, flat studio
expression, mismatched lighting direction, missing or wrong-direction shadow,
wrong scale, duplicated person, extra or missing limbs, distorted or swapped
face, over-smoothed plastic skin, nudity, suggestive posing, violence, extra
recognizable people in the scene.

{place_pose_negative}
