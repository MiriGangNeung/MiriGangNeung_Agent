"""결과 마감 (요구사항 E4, E6, E9).

- 요청 비율로 정확히 크롭한다.
- 'AI 생성 여행 미리보기'임을 PNG 메타데이터로 심는다. 화면상의 배지·면책 문구는
  프론트엔드가 표시하고(UI 설계서 4번 섹션), Gemini 결과에는 SynthID 워터마크가
  이미 들어 있다. 여기서는 파일 자체에 남는 표시를 담당한다.
"""

from __future__ import annotations

import io

from PIL import Image
from PIL.PngImagePlugin import PngInfo

from app.schemas.generation import AspectRatio

AI_DISCLOSURE = "AI 생성 여행 미리보기 (실제 방문 사진이 아닙니다)"


def finalize_image(
    data: bytes,
    aspect_ratio: AspectRatio,
    *,
    provider: str,
    model: str,
    prompt_version: str,
    place_id: str,
) -> tuple[bytes, int, int]:
    with Image.open(io.BytesIO(data)) as opened:
        image = opened.convert("RGB")
        cropped = _crop_to_ratio(image, aspect_ratio)

    metadata = PngInfo()
    metadata.add_text("Software", "MiriGangNeung AI")
    metadata.add_text("Description", AI_DISCLOSURE)
    metadata.add_text("AIGenerated", "true")
    metadata.add_text("AIProvider", provider)
    metadata.add_text("AIModel", model)
    metadata.add_text("PromptVersion", prompt_version)
    metadata.add_text("OnePickPlaceId", place_id)

    buffer = io.BytesIO()
    cropped.save(buffer, format="PNG", pnginfo=metadata)
    return buffer.getvalue(), cropped.width, cropped.height


def _crop_to_ratio(image: Image.Image, aspect_ratio: AspectRatio) -> Image.Image:
    ratio_w, ratio_h = aspect_ratio.wh
    target = ratio_w / ratio_h
    current = image.width / image.height

    if abs(current - target) < 1e-3:
        return image

    if current > target:
        # 너무 넓다 -> 좌우를 잘라낸다
        new_width = max(1, int(image.height * target))
        left = (image.width - new_width) // 2
        return image.crop((left, 0, left + new_width, image.height))

    # 너무 높다 -> 위아래를 잘라낸다
    new_height = max(1, int(image.width / target))
    top = (image.height - new_height) // 2
    return image.crop((0, top, image.width, top + new_height))
