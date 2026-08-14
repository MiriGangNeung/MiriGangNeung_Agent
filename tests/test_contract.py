"""백엔드 계약 고정 테스트.

여기 있는 값들은 백엔드 CompositionStatus enum과 09_AI_INTEGRATION.md의 retry 규칙에
직접 대응한다. 바꾸려면 백엔드 팀과 먼저 합의해야 하므로 테스트로 못 박아 둔다.
"""

from __future__ import annotations

import pytest

from app.core.errors import ERROR_SPECS, SAFETY_ERROR_CODES, AiServiceError
from app.schemas.generation import STAGE_LABELS, AspectRatio, JobStatus


def test_status_values_match_backend_enum():
    """백엔드 com.mirigangneung.composition.domain.CompositionStatus 와 동일해야 한다."""
    assert [s.value for s in JobStatus] == [
        "QUEUED",
        "ANALYZING",
        "COMPOSITING",
        "QUALITY_CHECK",
        "DONE",
        "FAILED",
    ]


@pytest.mark.parametrize(
    ("status", "coarse"),
    [
        (JobStatus.QUEUED, "RUNNING"),
        (JobStatus.ANALYZING, "RUNNING"),
        (JobStatus.COMPOSITING, "RUNNING"),
        (JobStatus.QUALITY_CHECK, "RUNNING"),
        (JobStatus.DONE, "DONE"),
        (JobStatus.FAILED, "FAILED"),
    ],
)
def test_coarse_status_matches_ai_integration_doc(status, coarse):
    assert status.coarse == coarse


def test_progress_is_monotonic_through_the_pipeline():
    order = [
        JobStatus.QUEUED,
        JobStatus.ANALYZING,
        JobStatus.COMPOSITING,
        JobStatus.QUALITY_CHECK,
        JobStatus.DONE,
    ]
    values = [s.progress for s in order]
    assert values == sorted(values)
    assert values[0] == 0
    assert values[-1] == 100


def test_every_status_has_a_korean_stage_label():
    for status in JobStatus:
        assert STAGE_LABELS[status]


def test_terminal_statuses():
    assert JobStatus.DONE.is_terminal
    assert JobStatus.FAILED.is_terminal
    assert not JobStatus.COMPOSITING.is_terminal


@pytest.mark.parametrize(
    "code",
    [
        "INVALID_IMAGE_FORMAT",
        "IMAGE_TOO_LARGE",
        "NO_PERSON_DETECTED",
        "MULTIPLE_PERSONS",
        "IMAGE_TOO_BLURRY",
        "FACE_OCCLUDED",
        "SAFETY_REJECTED_INPUT",
        "SAFETY_REJECTED_OUTPUT",
        "BUDGET_EXCEEDED",
    ],
)
def test_user_input_and_safety_errors_are_not_retryable(code):
    """09_AI_INTEGRATION.md: 안전성 거부는 자동 무한 retry 금지, 잘못된 입력은 retry 금지."""
    assert ERROR_SPECS[code].retryable is False


@pytest.mark.parametrize("code", ["PROVIDER_TIMEOUT", "PROVIDER_ERROR", "RATE_LIMITED"])
def test_transient_provider_errors_are_retryable(code):
    assert ERROR_SPECS[code].retryable is True


def test_safety_error_codes_are_registered():
    for code in SAFETY_ERROR_CODES:
        assert code in ERROR_SPECS


def test_unknown_error_code_falls_back_to_internal_error():
    error = AiServiceError("NOT_A_REAL_CODE")

    assert error.code == "INTERNAL_ERROR"
    assert error.http_status == 500


def test_error_payload_shape():
    payload = AiServiceError("NO_PERSON_DETECTED").to_payload()

    assert set(payload) == {"code", "message", "retryable"}
    assert payload["code"] == "NO_PERSON_DETECTED"
    assert payload["retryable"] is False


def test_supported_aspect_ratios_match_requirement_e4():
    """요구사항 E4: 1:1, 4:5, 9:16 을 지원해야 한다."""
    assert {r.value for r in AspectRatio} == {"1:1", "4:5", "9:16"}


def test_background_required_error_is_not_retryable():
    """실 프로바이더에서 실제 배경 없이 조용히 넘어가지 않기 위한 오류.

    사용자 입력 문제(백엔드가 배경을 안 보냄)이므로 재시도로 해결되지 않는다.
    """
    spec = ERROR_SPECS["BACKGROUND_REQUIRED"]

    assert spec.http_status == 400
    assert spec.retryable is False
