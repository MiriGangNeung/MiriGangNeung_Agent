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
    # 업로드 사진에서 얼굴만 잘라 확대한 참조 이미지 (선택).
    # 얼굴이 작게 찍힌 사진에서 합성 모델이 얼굴을 재구성해 다른 사람이 되는 것을
    # 막기 위한 보조 입력이다. 없으면 기존과 동일하게 두 장만 넘긴다.
    face_reference: bytes | None = None
    face_reference_mime: str = "image/png"


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


@dataclass
class BackgroundAnalysis:
    """이번 요청의 배경 이미지를 실시간으로 분석한 결과.

    `scripts/analyze_top_places.py`의 오프라인 `ImageAnalysis`와 필드명을 맞춰
    두 경로가 같은 모양의 데이터를 만들도록 한다 (`docs/adr/
    0004-realtime-background-analysis.md`). 오프라인 캐시(`place_insights.json`)가
    `onePickPlaceId`로 매칭되지 않을 때만 이 분석이 쓰인다 — 백엔드의
    award-photos/tourism-photos 탭에서 고른 배경은 Place UUID가 아닌 ID를 갖고
    있어 캐시에 애초에 매칭될 수 없기 때문이다.
    """

    scene_description: str = ""
    lighting: str = ""
    notable_features: tuple[str, ...] = field(default_factory=tuple)
    mood_tags: tuple[str, ...] = field(default_factory=tuple)


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
    async def analyze_background(self, image: bytes, mime: str) -> BackgroundAnalysis:
        """이번 요청의 배경 이미지에서 장면·조명·분위기를 추출한다.

        오프라인 VLM 사전분석 캐시(`place_insights.json`)가 `onePickPlaceId`로
        매칭되지 않을 때만 폴백으로 호출된다 (`app/jobs/runner.py`).
        """

    @abc.abstractmethod
    async def check_quality(
        self,
        image: bytes,
        mime: str,
        background: bytes | None = None,
        background_mime: str | None = None,
        subject: bytes | None = None,
        subject_mime: str | None = None,
    ) -> QualityVerdict:
        """생성 결과의 안전성·품질을 검사한다 (요구사항 E5).

        `background`를 함께 주면 원본 배경과 비교해 배경이 보존됐는지도 본다.
        결과만 봐서는 원래 간판에 뭐라 쓰여 있었는지 알 수 없어서, 합성 모델이
        한글 간판을 다른 글자로 다시 그려도 잡아내지 못했다.

        `subject`(업로드 인물 사진)까지 주면 얼굴이 그 사람인지 비교한다. 결과만
        보고 판정하던 `face_natural`은 "자연스러운 얼굴인가"만 물어서, 잘 그려진
        남의 얼굴을 그대로 통과시켰다.
        """


class ProviderTimeout(Exception):
    """공급자 호출이 제한 시간을 넘겼다. 제한 횟수 재시도 대상."""


class ProviderFailure(Exception):
    """공급자가 오류를 반환했다. 일시적이면 재시도 대상."""

    def __init__(self, message: str, *, retryable: bool = True):
        super().__init__(message)
        self.retryable = retryable
