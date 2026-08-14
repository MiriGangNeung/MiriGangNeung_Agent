"""이미지 전처리 (요구사항 B5).

- EXIF Orientation을 실제 픽셀에 적용한 뒤 EXIF/GPS/기기정보를 전량 제거한다.
- 모델 입력에 적합한 크기로 축소한다.

Pillow는 `Image.save()` 시 원본 info를 그대로 옮기지 않지만, 확실히 하기 위해
픽셀 데이터만 새 이미지로 옮겨 담아 메타데이터가 따라붙을 여지를 없앤다.
"""

from __future__ import annotations

import io

from PIL import Image, ImageOps

MAX_EDGE = 1536


def preprocess_photo(data: bytes, max_edge: int = MAX_EDGE) -> tuple[bytes, str]:
    """EXIF가 제거되고 크기가 조정된 PNG 바이트와 MIME을 돌려준다."""
    with Image.open(io.BytesIO(data)) as opened:
        rotated = ImageOps.exif_transpose(opened)
        rgb = rotated.convert("RGB")

        scale = min(1.0, max_edge / max(rgb.width, rgb.height))
        if scale < 1.0:
            rgb = rgb.resize(
                (max(1, int(rgb.width * scale)), max(1, int(rgb.height * scale))),
                Image.LANCZOS,
            )

        # 픽셀만 새 캔버스로 옮겨 EXIF/ICC/코멘트가 남지 않게 한다.
        clean = Image.new("RGB", rgb.size)
        clean.putdata(list(rgb.getdata()))

    buffer = io.BytesIO()
    clean.save(buffer, format="PNG")
    return buffer.getvalue(), "image/png"


def has_exif(data: bytes) -> bool:
    """테스트·검증용: 남아 있는 EXIF가 있는지 확인한다."""
    with Image.open(io.BytesIO(data)) as image:
        exif = image.getexif()
        return bool(exif)
