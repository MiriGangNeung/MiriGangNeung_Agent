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

## Body integrity (the whole person must be there)

- Render a complete, anatomically coherent figure: head, torso, both arms, both
  hands, both legs and both feet, all connected and in proportion.
- The body must never fade out, stop mid-torso, or dissolve into the
  background. The only acceptable reason for part of the body to be absent is
  the edge of the frame cutting it off.
- Occlusion has to be physically real. Only a solid object genuinely in front
  of the person may hide part of them, and only the part it actually covers.
  Through an open railing, fence bars, branches or tall grass you must still see
  the body in the gaps between them. Do not treat an object crossing the person
  as permission to omit everything below it.
- If the person stands behind a waist-high railing, their legs are still visible
  through it and their feet rest on the ground behind it. Whatever they carry — a
  bag, a cup — hangs from a hand or shoulder that is actually drawn, never in
  mid-air.

## Lighting (the person must be lit BY this scene, not lit separately)

The measurements below are a hint, not ground truth. **[background image] itself
is the authority on light** — read the actual light out of that photo and put
the person inside it.

- Measured hint: {time_of_day}, light from {light_direction} at a
  {light_angle} angle, {color_temperature} temperature, {shadow_hardness}
  shadows. These labels are frequently wrong. Where the photo disagrees — a dusk
  scene labelled "afternoon", golden foliage labelled "neutral", a backlit scene
  labelled "front" — the photo wins, every time.
- **Read the direction off the shadows, not off the label.** Find the shadows
  already in [background image] and see which way they fall. Shadows running
  toward the camera mean the light is behind the scene and the subject is
  backlit: their camera-facing side sits in shadow with a bright rim along the
  hair, shoulders and arms. Shadows running away from the camera mean front
  light. A dark canopy or dark foreground against a bright sky is backlight.
  Never front-light a person in a backlit scene — that single mistake is what
  makes a composite read as fake.
- **Color cast**: whatever color the light in the background actually is, the
  person's skin, hair and clothing carry that same cast. White or light-colored
  clothing takes on the scene's color; it must never stay clean neutral white in
  a scene that is golden, shaded, overcast or blue. This is the most common
  failure — a person correctly placed but still lit like a studio shot while
  everything around them is warm.
- **Exposure level**: the person is captured by the same camera at the same
  exposure as the background, so their midtones sit at the scene's level. In a
  dim, shaded or dusk scene the person is correspondingly dim. They must not be
  the brightest thing in the frame unless the background's own brightest light
  actually falls on them.
- **Shading the form**: the side facing away from the light goes genuinely dark,
  with occlusion under the chin, the arms and the hem. A flat, evenly lit figure
  reads as pasted on.
- **No invented light**: add no light source that is not in the background.
  Under a tree canopy or in shade the person receives only dim filtered ambient
  light — never a clean key light that no visible source could cast.
- Cast a correct contact shadow at the feet, in the same direction and with the
  same softness as the scene's existing shadows.

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
  location — a slight body turn, weight on one leg, mid-stride, looking out
  toward the view. Not a frontal, symmetrical, arms-at-side stance.
- **Hands**: vary them, and do not default to hands buried in pockets — that has
  become the repeated fallback and it makes every result look the same. Give the
  hands something ordinary to do: relaxed at the side, holding a bag strap or a
  cup, tucking hair back, one hand shading the eyes, resting on a railing that
  actually exists in the background.
- **Expression**: a genuine, warm expression for a good travel moment — a
  natural smile or soft candid look — not a flat studio expression.
- **Interaction with the scene**: the body should relate to the environment —
  facing along the shoreline, leaning toward the view, turned into the light.
- **Turn into the light**: where a dominant light source is visible in the
  background, angle the body toward it so the face and figure pick up its
  modelling, the way a photographer would actually stand someone. A
  three-quarter turn toward the light, with the camera-facing side falling into
  shadow, is what makes the person read as being in the scene.

This is repose, not replacement: same person, same face, same outfit, having a
good moment.

## Photographic style

{style_direction}

## Regeneration variation

{variation_direction}

## Identity (critical)

- Preserve the person's face, hairstyle, skin tone, build and clothing from
  [subject image]. Do not beautify, age, slim, or change any features.
- **Keep their actual body.** Height, weight, shoulder width, limb length and
  overall proportions come from [subject image] and stay as they are. Do not
  slim the waist, lengthen the legs, broaden the shoulders, straighten the
  posture into a model's, or otherwise idealise their physique. The person in
  the result should be recognisable to someone who knows them, from the body as
  much as the face.
- Keep the actual garments they are wearing — same cut, length, texture and
  colour. Do not substitute a different outfit.
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
edges, stiff frontal studio pose copied from the subject image, both hands
buried in pockets, flat studio expression, subject brighter than the scene
around them, clean neutral-white clothing in a warm or shaded scene, flat evenly
lit figure with no shadow side, key light or spotlight on the subject with no
visible source in the background, front-lit subject in a backlit scene,
mismatched lighting direction, missing or wrong-direction shadow, body fading
out or ending mid-torso, missing legs or feet, body hidden behind a see-through
railing or fence instead of showing through it, bag or object floating without a
hand holding it, slimmed waist, lengthened legs, idealised or restyled physique,
substituted outfit,
wrong scale, duplicated person, extra or missing limbs, distorted or swapped
face, over-smoothed plastic skin, nudity, suggestive posing, violence, extra
recognizable people in the scene.

{place_pose_negative}
