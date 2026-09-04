"""사진 스타일 분석 (요구사항 B6).

실패해도 Job 전체를 죽이지 않는다. 스타일 태그는 프롬프트 품질을 높이는 보조 정보일
뿐이므로, 분석이 안 되면 빈 목록으로 넘어가고 합성은 계속 진행한다.
"""

from __future__ import annotations

import logging

from app.providers.base import ImageCompositionProvider
from app.schemas.generation import StyleTag

logger = logging.getLogger(__name__)


async def analyze_style(
    provider: ImageCompositionProvider, image: bytes, mime: str
) -> list[StyleTag]:
    try:
        return await provider.analyze_style(image, mime)
    except Exception as exc:  # noqa: BLE001 - 보조 기능이므로 삼킨다
        logger.warning("스타일 분석에 실패해 태그 없이 진행합니다: %s", type(exc).__name__)
        return []
