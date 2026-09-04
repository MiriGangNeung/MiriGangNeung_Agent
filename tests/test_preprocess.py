"""전처리 (요구사항 B5): EXIF/GPS 제거와 방향 보정."""

from __future__ import annotations

import io

from PIL import Image

from app.pipeline.preprocess import has_exif, preprocess_photo


def _jpeg_with_exif(width: int = 400, height: int = 300) -> bytes:
    """Orientation과 GPS가 들어 있는 JPEG를 만든다."""
    image = Image.new("RGB", (width, height), (90, 140, 190))
    exif = image.getexif()
    exif[274] = 6  # Orientation: 90도 회전 필요
    exif[271] = "TestCamera"  # Make

    gps = exif.get_ifd(0x8825)
    gps[1] = "N"
    gps[2] = (37.0, 45.0, 0.0)  # 강릉 근처 위도
    gps[3] = "E"
    gps[4] = (128.0, 54.0, 0.0)

    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", exif=exif.tobytes())
    return buffer.getvalue()


def test_source_fixture_actually_carries_exif_and_gps():
    """이 테스트가 통과해야 아래 '제거' 테스트가 의미를 갖는다."""
    raw = _jpeg_with_exif()
    assert has_exif(raw) is True

    with Image.open(io.BytesIO(raw)) as image:
        assert dict(image.getexif().get_ifd(0x8825))


def test_removes_all_exif_including_gps():
    cleaned, mime = preprocess_photo(_jpeg_with_exif())

    assert mime == "image/png"
    assert has_exif(cleaned) is False

    with Image.open(io.BytesIO(cleaned)) as image:
        assert image.format == "PNG"
        assert not image.info.get("exif")
        assert not dict(image.getexif().get_ifd(0x8825))


def test_applies_orientation_to_pixels():
    """Orientation=6은 90도 회전이므로 가로/세로가 뒤바뀐다."""
    cleaned, _ = preprocess_photo(_jpeg_with_exif(400, 300))

    with Image.open(io.BytesIO(cleaned)) as image:
        assert (image.width, image.height) == (300, 400)


def test_downscales_to_max_edge():
    buffer = io.BytesIO()
    Image.new("RGB", (4000, 2000), (10, 10, 10)).save(buffer, format="PNG")

    cleaned, _ = preprocess_photo(buffer.getvalue(), max_edge=1000)

    with Image.open(io.BytesIO(cleaned)) as image:
        assert max(image.size) == 1000
        assert image.size == (1000, 500)


def test_keeps_small_images_untouched_in_size():
    buffer = io.BytesIO()
    Image.new("RGB", (320, 240), (10, 10, 10)).save(buffer, format="PNG")

    cleaned, _ = preprocess_photo(buffer.getvalue(), max_edge=1536)

    with Image.open(io.BytesIO(cleaned)) as image:
        assert image.size == (320, 240)
