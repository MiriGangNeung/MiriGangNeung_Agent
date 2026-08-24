"""Provider 어댑터 경계.

검토 총평 §3-5(외부 공급자 의존도)의 지적을 반영해, 합성·분석·품질검사 호출을 이
인터페이스 뒤로 숨긴다. 새 공급자는 이 ABC만 구현하면 파이프라인 수정 없이 붙는다.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field

from app.schemas.generation import AspectRatio, StyleTag


@dataclass
class CompositionRequest:
    person_image: bytes
    person_mime: str
    background_image: bytes
    background_mime: str
    prompt: str
    aspect_ratio: AspectRatio


@dataclass
class CompositionOutput:
    image: bytes
    mime: str = "image/png"
    estimated_cost_usd: float | None = None
    # 공급자가 자체 안전성 판정을 내려준 경우에만 채워진다.
    provider_safety_blocked: bool = False
    provider_safety_reason: str | None = None


@dataclass
class QualityVerdict:
    """요구사항 E5: 생성 결과의 유해성·인물 왜곡·신체 오류 판정."""

    passed: bool
    reason_code: str | None = None
    details: dict[str, object] = field(default_factory=dict)


class ImageCompositionProvider(abc.ABC):
    name: str
    image_model: str
    vision_model: str

    @property
    def estimated_cost_usd(self) -> float | None:
        """생성 전 요청 접수 시점에 알 수 있는 근사 비용 (검토 총평 §2-7).

        모델별 정액 근사치가 없는 공급자는 None을 반환한다. 실제 합성 이후의 값(공급자가
        `CompositionOutput.estimated_cost_usd`로 돌려주는 값)이 더 정확하면 그쪽이 최종
        기록을 덮어쓴다.
        """
        return None

    @abc.abstractmethod
    async def compose(self, request: CompositionRequest) -> CompositionOutput:
        """인물 사진 + 배경을 합성한다 (요구사항 E1~E4)."""

    @abc.abstractmethod
    async def analyze_style(self, image: bytes, mime: str) -> list[StyleTag]:
        """의상·색상·무드·포즈 태그를 신뢰도와 함께 추출한다 (요구사항 B6)."""

    @abc.abstractmethod
    async def check_quality(self, image: bytes, mime: str) -> QualityVerdict:
        """생성 결과의 안전성·품질을 검사한다 (요구사항 E5)."""


class ProviderTimeout(Exception):
    """공급자 호출이 제한 시간을 넘겼다. 제한 횟수 재시도 대상."""


class ProviderFailure(Exception):
    """공급자가 오류를 반환했다. 일시적이면 재시도 대상."""

    def __init__(self, message: str, *, retryable: bool = True):
        super().__init__(message)
        self.retryable = retryable
