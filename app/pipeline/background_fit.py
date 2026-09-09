"""합성 전에 배경을 요청 비율로 미리 잘라 둔다.

**왜 필요한가.** 지금까지 배경은 손대지 않고 그대로 넘기면서 출력 비율만
`ImageConfig(aspect_ratio=...)`로 강제했다. 그런데 한국관광공사 Type1 사진은 거의 다
가로 3:2인데 서비스가 요청하는 건 세로 4:5다. 그러면 모델은 "이 배경을 세로로
늘려서 채운 다음 인물을 넣어라"라는 지시를 받은 셈이 되고, **프레임의 절반 가까이를
지어내야 한다.**

안반데기 실측: 배경 940x626(3:2) → 결과 921x1152(4:5). 배경을 결과 폭에 맞추면
세로 613px, 즉 결과의 53%밖에 못 덮는다. 나머지 47%는 모델이 창작한 영역이고,
원본과의 행별 상관계수가 위쪽 하늘에서 0.99였다가 밭이 시작되는 지점부터 0.1로
무너진다. 사용자가 "배추밭이 뭉개졌다"고 지적한 띠가 정확히 그 경계였다 —
업스케일된 실제 픽셀과 지어낸 픽셀이 만나는 자리이고, 배추밭처럼 촘촘히 반복되는
질감은 생성 모델이 가장 못 버티는 대상이다.

**무엇을 하는가.** 배경을 목표 비율로 커버 크롭해서 넘긴다. 그러면 모델의 일이
"프레임을 47% 늘려라"에서 "이 프레임 안에 인물을 넣어라"로 바뀐다. 화각은 잘려
나가지만, 잘려나간 화각은 어차피 원본에 있던 진짜 픽셀이고 대안은 창작이었다.

해상도는 일부러 올리지 않는다. 업스케일은 없는 디테일을 만들어내지 못하면서
모델에 "이 정도 해상도의 정보가 있다"는 잘못된 신호만 준다.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass

from PIL import Image

from app.schemas.generation import AspectRatio

logger = logging.getLogger(__name__)

# 크롭 후 짧은 변이 이보다 작아지면 크롭을 포기한다. 잘라서 얻는 것(창작 제거)보다
# 잃는 것(모델이 쓸 픽셀 자체가 부족해짐)이 커지는 지점이다.
MIN_EDGE_AFTER_CROP = 320


@dataclass(frozen=True)
class BackgroundFit:
    image: bytes
    mime: str
    # 원본에서 잘려나간 면적 비율(0~1). 관측용이자 경고 판단용.
    cropped_away: float
    applied: bool
    reason: str = ""


def _anchor(zone: str | None) -> float:
    """배치 힌트에서 크롭 중심을 정한다. 0=왼쪽/위, 0.5=가운데, 1=오른쪽/아래.

    인물을 세울 자리가 프레임 왼쪽이라고 판정됐는데 가운데를 잘라내면, 정작
    세워야 할 지면이 잘려나간다.
    """
    text = (zone or "").lower()
    if "left" in text:
        return 0.3
    if "right" in text:
        return 0.7
    return 0.5


def fit_background_to_aspect(
    image_bytes: bytes,
    mime: str,
    aspect_ratio: AspectRatio,
    *,
    subject_zone: str | None = None,
) -> BackgroundFit:
    """배경을 `aspect_ratio`로 커버 크롭한다. 이미 비율이 맞으면 그대로 돌려준다."""
    try:
        image = Image.open(io.BytesIO(image_bytes))
        image.load()
    except Exception:  # noqa: BLE001 - 배경이 깨졌으면 여기서 판단하지 않는다
        logger.warning("배경 이미지를 열 수 없어 비율 보정을 건너뜁니다.")
        return BackgroundFit(image_bytes, mime, 0.0, False, "decode-failed")

    ratio_w, ratio_h = aspect_ratio.wh
    target = ratio_w / ratio_h
    current = image.width / image.height
    # 1% 이내면 손대지 않는다. 재인코딩으로 잃는 게 더 크다.
    if abs(current - target) / target < 0.01:
        return BackgroundFit(image_bytes, mime, 0.0, False, "already-matching")

    if current > target:  # 원본이 더 넓다 → 좌우를 자른다
        new_w, new_h = round(image.height * target), image.height
    else:  # 원본이 더 높다 → 위아래를 자른다
        new_w, new_h = image.width, round(image.width / target)

    if min(new_w, new_h) < MIN_EDGE_AFTER_CROP:
        logger.info(
            "크롭하면 짧은 변이 %dpx라 비율 보정을 건너뜁니다 (원본 %dx%d, 목표 %s).",
            min(new_w, new_h),
            image.width,
            image.height,
            aspect_ratio.value,
        )
        return BackgroundFit(image_bytes, mime, 0.0, False, "too-small-after-crop")

    anchor = _anchor(subject_zone)
    left = round((image.width - new_w) * anchor)
    top = round((image.height - new_h) * anchor)
    cropped = image.convert("RGB").crop((left, top, left + new_w, top + new_h))

    buffer = io.BytesIO()
    cropped.save(buffer, format="JPEG", quality=95, subsampling=0)
    cropped_away = 1 - (new_w * new_h) / (image.width * image.height)
    logger.info(
        "배경을 %s에 맞춰 %dx%d → %dx%d로 잘랐습니다 (원본의 %.0f%% 사용).",
        aspect_ratio.value,
        image.width,
        image.height,
        new_w,
        new_h,
        100 * (1 - cropped_away),
    )
    return BackgroundFit(buffer.getvalue(), "image/jpeg", cropped_away, True)
