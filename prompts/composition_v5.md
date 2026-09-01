---
version: v5
purpose: 인물 사진 + 강릉 관광지 배경 합성 (요구사항 E1~E4), 사전 분석된 배경 이미지의
  구조화된 배치/조명/카메라 데이터로 정확한 합성 지시. 구조화 데이터가 없는 경우
  (개발 카탈로그·실시간 분석·백엔드 텍스트 필드 폴백)는 scene_hint/lighting_hint와
  일반적인 기본 문구로 대체된다.
changes_from_v4: |
  실사용 결과 리뷰에서 나온 네 가지를 반영했다.
  1. 신체 비율 붕괴 — 송정해변 결과가 5.6등신, 정동심곡 결과는 상·하체 비율이 무너졌다.
     v4에는 인체 비율에 대한 수치 제약이 아예 없었고, Identity 절이 "limb length와
     비율은 [subject image]에서 가져오라"고 지시했는데 업로드 사진은 대개 상반신이라
     다리가 보이지 않는다. 즉 모델에게 존재하지 않는 근거를 참조하라고 시킨 셈이다.
     Figure proportion 절을 신설해 등신·다리 길이·머리 크기를 수치로 못박았다.
  2. 배경 스케일 붕괴 — 정동심곡에서 인물에 맞춰 데크와 난간의 원근이 재구성됐다.
     Perspective & scale에 '알려진 크기의 물체로 검산', '인물을 넣으려고 장면을
     리사이즈하지 말 것'을 추가했다.
  3. 설 수 없는 곳 배치 — 구룡폭포 결과가 데이터상 지정된 평평한 바위(center-left,
     화면 높이 25%)를 무시하고 경사 바위 위에 화면 높이 75%로 놓였다. subject_zone의
     크기 지시가 위치 문장에 묻혀 무시되던 것을 별도 지시로 분리했다.
  4. 얼굴 변형 — Identity 절을 '얼굴이 곧 정체성'으로 다시 씀. 사용자가 말한
     '형상 유지'는 체형이 아니라 얼굴을 뜻한다.
  추가로 Notion '미리강릉 포즈 조사3(사람들 옷)' 데이터셋을 Outfit 절로 반영했다.
inputs: [person_image, background_image, place_name, scene_hint, lighting_hint, placement,
  lighting, camera, mood_tags, color_palette, style_tags, aspect_ratio, variation_mode,
  outfit_direction]
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
- **{ground_plane} is a specific surface that is actually in this photo — find
  it before you place anyone.** It was chosen by looking at this exact image.
  Putting the person on a different surface because it is nearer the middle of
  the frame, or roomier, is the mistake to avoid.
- They must have both feet on a surface a person could really stand on. Never
  place them on water, surf, wet or loose rocks, riprap, a sloping or rounded
  boulder, or an active roadway — even if that is what fills the foreground. A
  surface only counts if it is level enough to stand on with both feet flat.
  If the named surface is not clearly visible, move them to the nearest part of
  the frame where someone could plausibly stand, rather than floating them over
  the foreground.
- **Do not build ground that is not there.** No invented step, ledge, path,
  railing, platform or flattened rock to stand the person on.
- Keep {occluding_elements} in front of the person so they are partially
  occluded naturally. If there is nothing to occlude with, place the person
  fully unobstructed.

## Figure proportion (non-negotiable human anatomy)

Getting this wrong is the single most visible failure. A figure whose legs are
too short for its head does not read as a real person no matter how good the
lighting is.

- A standing adult is **7 to 7.5 head-heights tall**. Measure it: the head from
  crown to chin fits into the full standing height at least seven times. Six or
  fewer is a deformed figure, not a short person.
- **The legs are half the person.** The crotch sits at roughly the midpoint of
  standing height; hip to heel is about 50% of total height, and the knee is
  halfway down that. A figure whose legs are visibly shorter than its head-plus-
  torso is wrong.
- Shoulders are about two head-widths across. The head is small relative to the
  body — never enlarge it to make the face more readable.
- **[subject image] usually shows only the head and upper body.** Its framing is
  not evidence about leg length, and you must not infer proportions from it.
  Build the unseen lower body to the ratios above.
- Never compress the lower body to fit the space available. If a correctly
  proportioned figure does not fit where you placed them, make the whole person
  smaller or let the frame edge cut them off — do not shorten the legs, shrink
  the shins, or sink the feet into the ground.

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
- **Size in frame**: "{subject_zone}" states where the person goes *and how big
  they are*. When it gives a fraction of frame height, that is the person's
  entire head-to-heel span — "~25% of frame height" means the whole figure is a
  quarter of the image tall, a small figure standing in a wide scene. Rendering
  them at two or three times that size is what destroys the scene's scale.
- **Check the height against something of known size** already in the photo: a
  handrail or guardrail is about 1.1 m, a stair riser 15 cm, a deck plank 12 cm
  wide, a door 2 m, a car 1.5 m tall, a bench seat 45 cm, and any adult already
  in the background is 1.6–1.8 m. Compare the person you drew against at least
  one of these. If a waist-high railing reaches their chest, or their head clears
  a doorway, the figure is the wrong size — fix the person.
- **Never resize the scene to fit the person.** The path, deck, steps, railing
  and their perspective are fixed by [background image]. If the person looks too
  large for the spot, shrink the person; do not widen the walkway, enlarge the
  planks, push the railing back, or bend the vanishing lines around them.

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
good moment. Re-posing never licenses re-proportioning — the figure that ends up
in the scene obeys the head-height ratios above whatever pose it takes.

## Photographic style

{style_direction}

## Regeneration variation

{variation_direction}

## Identity — the face (most critical rule in this prompt)

**The face is the deliverable.** This photo is made so one specific person can
see themselves somewhere in Gangneung. A beautiful result with someone else's
face is a total failure, worse than an ugly result with the right face.

- Copy the face from [subject image] feature by feature: face shape and width,
  jawline and chin, eye shape, size and spacing, eyelid form, eyebrow shape and
  thickness, nose bridge and tip, mouth width and lip thickness, ear position,
  skin tone and skin texture, hairline, and hairstyle. Someone who knows this
  person must recognise them immediately.
- **Do not drift toward a generic attractive face.** Specifically forbidden:
  enlarging the eyes, narrowing or sharpening the jaw, slimming the nose,
  raising the cheekbones, smoothing away pores, moles, freckles, scars, lines or
  asymmetry, whitening the skin, and replacing the hairstyle. Real faces are
  asymmetric and textured; keep that.
- Do not change their apparent gender, ethnicity, or age. Do not remove or add
  glasses, facial hair or hair length.
- **Build**: keep the visible build — weight, shoulder width, torso shape — as it
  appears in [subject image]. Do not slim the waist or broaden the shoulders. The
  parts of the body the photo does not show are constructed from the Figure
  proportion rules above, not invented as a fashion-model physique.
- Identity is about *who they are*, not *how they are standing* — changing the
  pose, body angle and expression as directed above is required, not a
  violation of this rule.

## Outfit

{outfit_direction}

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
hand holding it, slimmed waist, idealised or restyled physique,
wrong scale, duplicated person, extra or missing limbs, over-smoothed plastic
skin, nudity, suggestive posing, violence, extra recognizable people in the
scene,
short-legged or squat figure, six-heads-tall or shorter figure, oversized head,
legs shorter than the head-and-torso, dwarfed or compressed lower body,
person out of scale with the railing/steps/deck/doorway beside them,
walkway, deck, railing or path resized or re-perspectived to fit the person,
invented ground, step or ledge under the feet, person on a sloping or rounded
boulder,
swapped or generic beautified face, enlarged eyes, slimmed jaw, sharpened nose,
whitened or airbrushed skin, removed moles/freckles/asymmetry, changed
hairstyle,
{outfit_negative}

{place_pose_negative}
