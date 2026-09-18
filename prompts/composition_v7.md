---
version: v7
changes_from_v6: |
  사용자가 54장 스윕 결과 중 7장을 직접 기준 미달로 골라 사유를 적어줬다
  (test_results/Fail/개선해야할 점.txt). 반영 전에 각 건을 원본 배경 사진·
  place_insights.json 원자료와 대조해 원인을 확인했다.

  실제로 프롬프트로 고칠 수 있는 결함은 세 갈래였다.

  1. 근접한 랜드마크를 크기 기준으로 오인 (월화거리 아치, 주문진등대#1, 향호해변
     버스정류장) — v6의 "먼 랜드마크는 크기 기준이 아니다"는 문자 그대로 distant한
     것에만 적용되게 쓰여 있어서, 안반데기 풍력발전기처럼 멀리 있는 것은 걸러도
     화면 가까이 있는 아치·등대·버스정류장 지붕처럼 눈에 띄는 구조물은 안 걸렀다.
     이런 구조물은 오히려 실제 크기를 아는 인공물이므로, "크기 기준 아님"이 아니라
     "알려진 크기 목록에 넣어서 정확히 재라"로 바꿔야 했다. 목록에 버스정류장·
     아치형 캐노피·등대탑을 추가했다.
  2. 있지도 않은 곳에 구조물을 새로 만들어 붙임 (대관령박물관) — 원본 사진에서
     격자무늬 난간은 진입 목교 위에만 있고, 사람이 배치된 개방된 광장 쪽에는
     없다. 그런데 결과물은 그 목교 난간 디자인을 광장 쪽으로 그대로 옮겨 붙였다.
     v6의 "없는 것을 지어내지 말라"는 바닥(계단/단/난간)에 대해서만 명시돼 있었고
     "장면의 다른 곳에 있는 구조물을 이 위치로 복제하지 말라"는 없었다. 추가했다.
  3. 낮은 난간을 사람이 걸치듯 배치 (경포가시연습지) — 원본의 난간은 허리보다
     낮은 장식용 난간이다. v6의 신체 보존 규칙은 "허리 높이 난간"을 예시로 들며
     다리가 비쳐 보여야 한다고만 했지, 그보다 낮은 난간에 사람이 걸터앉거나
     관통하듯 겹쳐 그려지는 것을 별도로 금지하지 않았다. 낮은 난간은 사람이
     넘어서거나 걸치는 대상이 아니라 완전히 그 뒤/앞에 서는 경계선이라고 못박았다.

  반영하지 않은 것 (근거 없음 또는 프롬프트로 못 고침):
  - 임당동 성당#1 "형상이 기울어짐" — 원본 사진(tong.visitkorea.or.kr
    /cms2/website/12/2828212.jpg)을 직접 받아 확인하니 광각 로우앵글로 찍은
    원본 자체가 이미 이 정도로 기울어져 있다. "배경을 있는 그대로 쓰라"는
    지시를 지킨 결과이지 합성 결함이 아니다. 프롬프트로 고치면 오히려 배경
    보존 원칙과 충돌한다 — 이 사진을 계속 쓸지는 장소 사진 큐레이션 문제로
    별도 판단이 필요하다.
  - 주문진등대#0 "울타리를 뚫음/서는 위치가 틀림" — place_insights.json의
    suggestedSubjectZone이 애초에 목교가 아니라 "광장 오른쪽"을 가리키고
    있었다. 목교 위에 세워야 한다는 사용자 판단이 맞다면 이건 이 프롬프트
    템플릿이 아니라 해당 장소의 사전 분석(placement) 데이터를 다시 뽑아야
    하는 문제다 — 여기서 같이 고치면 다른 장소의 정상 배치까지 건드리게 된다.
legacy_version: v6
purpose: 인물 사진 + 강릉 관광지 배경 합성 (요구사항 E1~E4), 사전 분석된 배경 이미지의
  구조화된 배치/조명/카메라 데이터로 정확한 합성 지시. 구조화 데이터가 없는 경우
  (개발 카탈로그·실시간 분석·백엔드 텍스트 필드 폴백)는 scene_hint/lighting_hint와
  일반적인 기본 문구로 대체된다.
changes_from_v5: |
  안반데기 결과에서 "풍차와 사람의 원근이 무시됐다"는 지적을 받았다. 인물 크기는
  subject_zone이 지시한 ~40%를 지켰는데도 사람이 풍경을 압도해 보였다.

  원인은 v5의 크기 검산이 **알려진 크기의 인공물**(난간 1.1m, 문 2m, 차량 1.5m)에만
  기대고 있었다는 것이다. 밭·해변·능선처럼 그런 물체가 하나도 없는 장면에서는
  검산할 대상이 없어, 모델이 멀리 있는 큰 지형지물(풍력발전기)에 사람을 맞춘다.
  발전기는 크고 멀리 있어서 화면상 크기가 사람 크기에 대해 아무것도 말해주지 않는다.

  그래서 기준 물체가 없어도 항상 성립하는 앵커를 넣었다 — 카메라가 eye-level이면
  같은 지면에 선 성인의 눈높이는 거리와 무관하게 지평선 위에 온다(투영 기하의 결과).
  코드가 horizonPosition과 subject_zone의 %를 합쳐 머리 상단·발의 화면 위치를
  수치로 계산해 {perspective_anchor}로 넣는다. 앙각·부감이거나 지평선 위치를 모르면
  수치를 지어내지 않고 일반 문장만 넣는다.

  더불어 "열린 풍경에는 기준 물체가 없다", "먼 랜드마크는 크기 기준이 아니다"를
  명시했다.
inputs: [person_image, background_image, place_name, scene_hint, lighting_hint, placement,
  lighting, camera, mood_tags, color_palette, style_tags, aspect_ratio, variation_mode,
  outfit_direction]
---

You are given these input images, in order:
- [subject image]: an uploaded photo of a real user (the person).
{face_reference_note}- [background image]: a real tourist-site photo of {place_name} in Gangneung, South Korea, fetched from a URL.

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
- **Do not copy a structure from elsewhere in the photo to where the person
  stands.** A railing, fence or lattice visible on a bridge, a different path,
  or the far side of the scene stays where it actually is. If the spot named by
  {subject_zone} has no such structure around it, do not add one there just
  because one exists somewhere else in the frame — an open plaza or walkway
  stays open.
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
- **A railing lower than the waist is a boundary line, not a perch.** The
  person stands or sits fully on one side of it — never straddling it, leaning
  through its rail, or drawn overlapping its top bar so it looks like they are
  pushing through it. If they rest a hand on it, only the hand touches it; the
  rest of the body stays clear of its plane.

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
{perspective_anchor}
- **Check the height against something of known size** already in the photo: a
  handrail or guardrail is about 1.1 m, a stair riser 15 cm, a deck plank 12 cm
  wide, a door 2 m, a car 1.5 m tall, a bench seat 45 cm, a bus shelter is about
  2.2–2.5 m to the roofline, an overhead arch, pergola or street canopy is
  typically 3.5–5 m clear of the ground (well above head height, not something a
  standing person reaches close to), a lighthouse or tower is several times a
  person's height even at moderate distance, and any adult already in the
  background is 1.6–1.8 m. Compare the person you drew against at least one of
  these. If a waist-high railing reaches their chest, a bus shelter roof sits at
  their hairline, or their head reaches even a third of the way up a lighthouse
  or tower, the figure is the wrong size — fix the person.
- **Open landscapes have no such object.** A field, a beach, a ridge or a
  waterfall gives you nothing man-made to measure against, and that is exactly
  where the figure ends up looking pasted on. In those scenes the horizon rule
  above is the only anchor you have — use it instead of guessing.
- **A landmark's visual prominence is not a size reference, near or far.** A
  wind turbine, a pavilion, a lighthouse, a far ridge, or a bus shelter/archway
  right next to the subject is a real object with a real size (use the list
  above), but matching the person to how large it *looks* in the frame is
  backwards — that is what makes a person tower over a lighthouse or dwarf a bus
  shelter. Look up or reason out the object's actual size, then scale the
  person to it; never scale the person to the object's screen footprint.
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

{face_reference_direction}

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
fence, railing or lattice copied in from another part of the scene where it
does not actually exist, person straddling or overlapping a low railing's rail
line instead of standing fully behind it, person scaled to match a nearby
landmark's apparent screen size, person as tall as or taller than a bus
shelter/archway/lighthouse in the background,
swapped or generic beautified face, enlarged eyes, slimmed jaw, sharpened nose,
whitened or airbrushed skin, removed moles/freckles/asymmetry, changed
hairstyle,
{outfit_negative}

{place_pose_negative}
