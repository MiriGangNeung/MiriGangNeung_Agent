"""백엔드 계약 스키마.

status 값은 백엔드 `CompositionStatus` enum과 1:1로 정렬한다 (새 값을 만들지 않는다).
`coarseStatus`는 09_AI_INTEGRATION.md의 축약형(RUNNING|DONE|FAILED)이며, 두 문서가
어긋나지 않도록 함께 실어 보낸다.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    QUEUED = "QUEUED"
    ANALYZING = "ANALYZING"
    COMPOSITING = "COMPOSITING"
    QUALITY_CHECK = "QUALITY_CHECK"
    DONE = "DONE"
    FAILED = "FAILED"

    @property
    def is_terminal(self) -> bool:
        return self in (JobStatus.DONE, JobStatus.FAILED)

    @property
    def coarse(self) -> str:
        if self is JobStatus.DONE:
            return "DONE"
        if self is JobStatus.FAILED:
            return "FAILED"
        return "RUNNING"

    @property
    def progress(self) -> int:
        return _PROGRESS[self]


_PROGRESS: dict[JobStatus, int] = {
    JobStatus.QUEUED: 0,
    JobStatus.ANALYZING: 25,
    JobStatus.COMPOSITING: 55,
    JobStatus.QUALITY_CHECK: 80,
    JobStatus.DONE: 100,
    JobStatus.FAILED: 100,
}

# 프론트엔드 '합성 단계 타임라인'(UI 설계서 3번 섹션)에 그대로 노출되는 한국어 문구
STAGE_LABELS: dict[JobStatus, str] = {
    JobStatus.QUEUED: "요청 접수",
    JobStatus.ANALYZING: "사진과 배경 분석 중",
    JobStatus.COMPOSITING: "이미지 합성 중",
    JobStatus.QUALITY_CHECK: "안전성 및 품질 확인 중",
    JobStatus.DONE: "완료",
    JobStatus.FAILED: "실패",
}


class SafetyStatus(str, Enum):
    PASSED = "PASSED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"


class AspectRatio(str, Enum):
    """요구사항 E4: SNS에 적합한 비율."""

    SQUARE = "1:1"
    PORTRAIT = "4:5"
    STORY = "9:16"

    @property
    def wh(self) -> tuple[int, int]:
        return _RATIO_WH[self]


_RATIO_WH: dict[AspectRatio, tuple[int, int]] = {
    AspectRatio.SQUARE: (1, 1),
    AspectRatio.PORTRAIT: (4, 5),
    AspectRatio.STORY: (9, 16),
}


class StyleTag(BaseModel):
    """요구사항 B6: 태그 + 신뢰도 점수."""

    category: str
    value: str
    confidence: float = Field(ge=0.0, le=1.0)


class GenerationResult(BaseModel):
    imageReference: str
    width: int
    height: int
    aspectRatio: AspectRatio


class SafetyReport(BaseModel):
    status: SafetyStatus = SafetyStatus.UNKNOWN
    reasonCode: str | None = None


class ErrorPayload(BaseModel):
    code: str
    message: str
    retryable: bool


class GenerationMetadata(BaseModel):
    """요구사항 E9: 생성 이력에 남겨야 하는 값들."""

    provider: str
    model: str
    promptVersion: str
    onePickPlaceId: str
    createdAt: str
    completedAt: str | None = None
    durationMs: int | None = None
    styleTags: list[StyleTag] = Field(default_factory=list)
    estimatedCostUsd: float | None = None
    attempts: int = 0


class GenerationJobResponse(BaseModel):
    providerJobId: str
    status: JobStatus
    coarseStatus: str
    stage: str
    progress: int
    result: GenerationResult | None = None
    safety: SafetyReport = Field(default_factory=SafetyReport)
    error: ErrorPayload | None = None
    metadata: GenerationMetadata


class MetaResponse(BaseModel):
    provider: str
    imageModel: str
    visionModel: str
    promptVersion: str
    supportedAspectRatios: list[AspectRatio]
    maxUploadBytes: int
    resultTtlSeconds: int


class HealthResponse(BaseModel):
    status: str
    jobStore: str
    provider: str
