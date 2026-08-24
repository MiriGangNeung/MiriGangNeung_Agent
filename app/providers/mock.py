"""API 키 없이 전체 파이프라인을 돌리기 위한 Mock 공급자.

Phase 1의 목적은 백엔드·프론트가 Gemini 키나 비용 없이 통합 작업을 시작하는 것이다.
실제 모델을 부르는 대신 배경 위에 인물 사진을 합성한 '그럴듯한' 결과를 만들어 준다.
"""

from __future__ import annotations

import asyncio
import io

from PIL import Image

from app.providers.base import (
    CompositionOutput,
    CompositionRequest,
    ImageCompositionProvider,
    QualityVerdict,
)
from app.schemas.generation import StyleTag

# 실제 생성이 30초 안팎이라 프론트의 로딩 타임라인이 의미 있게 보이도록 약간 지연시킨다.
MOCK_COMPOSE_DELAY_SECONDS = 1.5


class MockProvider(ImageCompositionProvider):
    name = "mock"
    image_model = "mock-composite-v1"
    vision_model = "mock-vision-v1"

    @property
    def estimated_cost_usd(self) -> float | None:
        return 0.0

    async def compose(self, request: CompositionRequest) -> CompositionOutput:
        await asyncio.sleep(MOCK_COMPOSE_DELAY_SECONDS)

        background = Image.open(io.BytesIO(request.background_image)).convert("RGB")
        person = Image.open(io.BytesIO(request.person_image)).convert("RGBA")

        ratio_w, ratio_h = request.aspect_ratio.wh
        canvas_h = 1280
        canvas_w = int(canvas_h * ratio_w / ratio_h)
        canvas = _cover_resize(background, canvas_w, canvas_h)

        # 인물을 캔버스 높이의 60%로 줄여 하단 중앙에 얹는다.
        target_h = int(canvas_h * 0.6)
        target_w = max(1, int(person.width * target_h / person.height))
        person = person.resize((target_w, target_h), Image.LANCZOS)
        canvas.paste(person, ((canvas_w - target_w) // 2, canvas_h - target_h), person)

        buffer = io.BytesIO()
        canvas.save(buffer, format="PNG")
        return CompositionOutput(
            image=buffer.getvalue(), estimated_cost_usd=self.estimated_cost_usd
        )

    async def analyze_style(self, image: bytes, mime: str) -> list[StyleTag]:
        return [
            StyleTag(category="mood", value="감성적", confidence=0.5),
            StyleTag(category="outfit", value="캐주얼", confidence=0.5),
        ]

    async def check_quality(self, image: bytes, mime: str) -> QualityVerdict:
        return QualityVerdict(passed=True, details={"provider": "mock"})


def _cover_resize(image: Image.Image, width: int, height: int) -> Image.Image:
    """비율을 유지하며 대상 크기를 덮도록 확대한 뒤 중앙을 잘라낸다."""
    scale = max(width / image.width, height / image.height)
    resized = image.resize(
        (max(1, int(image.width * scale)), max(1, int(image.height * scale))),
        Image.LANCZOS,
    )
    left = (resized.width - width) // 2
    top = (resized.height - height) // 2
    return resized.crop((left, top, left + width, top + height))
