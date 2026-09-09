"""배경 비율 보정 (app/pipeline/background_fit.py).

이 모듈이 없을 때 실제로 난 문제: 안반데기 배경 940x626(가로 3:2)으로 4:5 세로를
요청하니 모델이 프레임의 47%를 지어냈고, 지어낸 영역과 원본 영역이 만나는 띠에서
배추밭 질감이 뭉갰다. 그래서 여기서 지키는 것은 "잘린 결과가 정확히 목표 비율일 것"
하나다 — 그래야 모델이 채워 넣을 여백이 남지 않는다.
"""

from __future__ import annotations

import io

import pytest
from PIL import Image

from app.pipeline.background_fit import MIN_EDGE_AFTER_CROP, fit_background_to_aspect
from app.schemas.generation import AspectRatio


def _png(width: int, height: int) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (10, 120, 40)).save(buffer, format="PNG")
    return buffer.getvalue()


def _size(data: bytes) -> tuple[int, int]:
    return Image.open(io.BytesIO(data)).size


@pytest.mark.parametrize(
    "aspect",
    [AspectRatio.SQUARE, AspectRatio.PORTRAIT, AspectRatio.STORY],
)
def test_가로_사진을_목표_비율로_정확히_맞춘다(aspect: AspectRatio) -> None:
    fit = fit_background_to_aspect(_png(940, 626), "image/png", aspect)

    assert fit.applied
    width, height = _size(fit.image)
    ratio_w, ratio_h = aspect.wh
    # 반올림 오차 1px까지만 허용한다. 남는 여백은 곧 모델이 지어낼 영역이다.
    assert abs(width / height - ratio_w / ratio_h) < 0.01


def test_세로가_긴_사진은_위아래를_자른다() -> None:
    fit = fit_background_to_aspect(_png(900, 1600), "image/png", AspectRatio.PORTRAIT)

    width, height = _size(fit.image)
    assert (width, height) == (900, 1125)
    assert fit.cropped_away == pytest.approx(1 - 1125 / 1600, abs=0.01)


def test_이미_비율이_맞으면_다시_인코딩하지_않는다() -> None:
    original = _png(800, 1000)  # 정확히 4:5

    fit = fit_background_to_aspect(original, "image/png", AspectRatio.PORTRAIT)

    assert not fit.applied
    assert fit.image is original
    assert fit.mime == "image/png"


def test_너무_작아지면_자르지_않는다() -> None:
    # 9:16(0.5625)으로 자르면 폭이 height*0.5625 가 된다. 높이 500이면 281px라
    # MIN_EDGE_AFTER_CROP 아래다. 창작을 막자고 모델이 쓸 픽셀 자체를 없애는 건 손해다.
    wide = _png(2000, 500)
    assert round(500 * 9 / 16) < MIN_EDGE_AFTER_CROP

    fit = fit_background_to_aspect(wide, "image/png", AspectRatio.STORY)

    assert not fit.applied
    assert fit.reason == "too-small-after-crop"


def test_배치_힌트가_크롭_위치를_옮긴다() -> None:
    """인물을 세울 자리가 왼쪽이면 왼쪽을 남겨야 한다."""
    source = Image.new("RGB", (1000, 500))
    for x in range(1000):
        for y in range(0, 500, 100):
            source.putpixel((x, y), (x % 256, 0, 0))
    buffer = io.BytesIO()
    source.save(buffer, format="PNG")
    data = buffer.getvalue()

    left = fit_background_to_aspect(
        data, "image/png", AspectRatio.SQUARE, subject_zone="lower-left, ~30%"
    )
    right = fit_background_to_aspect(
        data, "image/png", AspectRatio.SQUARE, subject_zone="lower-right, ~30%"
    )

    assert left.applied and right.applied
    assert _size(left.image) == _size(right.image)
    # 같은 크기를 잘랐지만 창이 다른 곳에 있어야 한다.
    assert left.image != right.image


def test_깨진_이미지는_그대로_넘긴다() -> None:
    fit = fit_background_to_aspect(b"not an image", "image/png", AspectRatio.PORTRAIT)

    assert not fit.applied
    assert fit.image == b"not an image"
    assert fit.reason == "decode-failed"
