"""계약 E2E: POST -> 폴링 -> 결과 바이트.

백엔드 HttpAiGenerationClient가 밟게 될 경로를 그대로 따라간다.
사진 검증(B3/B4)은 별도 유닛 테스트가 담당하므로 여기서는 통과시킨다.
"""

from __future__ import annotations

import io
import time

import pytest
from PIL import Image

from app.pipeline.validate import FaceBox, ValidationReport
from app.schemas.generation import JobStatus
from tests.conftest import TEST_API_KEY, make_image_bytes

TERMINAL = {JobStatus.DONE.value, JobStatus.FAILED.value}


@pytest.fixture(autouse=True)
def _bypass_photo_validation(monkeypatch):
    monkeypatch.setattr(
        "app.api.routes_generation.validate_photo",
        lambda data, mime, **kwargs: ValidationReport(
            format="PNG", width=640, height=800, face=FaceBox(100, 100, 200, 200), sharpness=99.0
        ),
    )


def _submit(client, *, place="anmok-beach", ratio="4:5", **extra):
    files = {"photo": ("photo.jpg", make_image_bytes(), "image/jpeg")}
    data = {"onePickPlaceId": place, "aspectRatio": ratio, **extra}
    return client.post("/v1/generations", files=files, data=data)


def _poll_until_terminal(client, job_id: str, timeout: float = 15.0) -> dict:
    deadline = time.time() + timeout
    payload: dict = {}
    while time.time() < deadline:
        response = client.get(f"/v1/generations/{job_id}")
        assert response.status_code == 200
        payload = response.json()
        if payload["status"] in TERMINAL:
            return payload
        time.sleep(0.05)
    pytest.fail(f"Job이 제한 시간 내에 끝나지 않았습니다: {payload.get('status')}")


def test_health_is_open_without_api_key(client):
    client.headers.pop("X-API-Key", None)
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "jobStore": "memory", "provider": "mock"}


def test_requires_api_key(client):
    client.headers.update({"X-API-Key": "wrong-key"})
    response = _submit(client)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


def test_meta_reports_supported_aspect_ratios(client):
    payload = client.get("/v1/meta").json()

    assert payload["supportedAspectRatios"] == ["1:1", "4:5", "9:16"]
    assert payload["promptVersion"] == "v1"
    assert payload["provider"] == "mock"


def test_full_generation_roundtrip(client):
    created = _submit(client)
    assert created.status_code == 202

    body = created.json()
    job_id = body["providerJobId"]
    assert body["status"] == JobStatus.QUEUED.value
    assert body["coarseStatus"] == "RUNNING"
    assert body["progress"] == 0
    assert body["metadata"]["onePickPlaceId"] == "anmok-beach"
    assert body["metadata"]["promptVersion"] == "v1"

    final = _poll_until_terminal(client, job_id)
    assert final["status"] == JobStatus.DONE.value, final.get("error")
    assert final["coarseStatus"] == "DONE"
    assert final["progress"] == 100
    assert final["error"] is None
    assert final["result"]["imageReference"] == f"/v1/generations/{job_id}/result"
    assert final["metadata"]["durationMs"] is not None
    assert final["metadata"]["attempts"] == 1

    result = client.get(f"/v1/generations/{job_id}/result")
    assert result.status_code == 200
    assert result.headers["content-type"] == "image/png"
    assert "attachment" in result.headers["content-disposition"]
    assert result.headers["X-AI-Generated"] == "true"

    with Image.open(io.BytesIO(result.content)) as image:
        assert image.format == "PNG"
        # 요구사항 E4: 요청한 4:5 비율로 나와야 한다.
        assert round(image.width / image.height, 3) == round(4 / 5, 3)
        # 요구사항 E6: 파일에 AI 생성 표시가 남아 있어야 한다.
        assert image.info["AIGenerated"] == "true"
        assert image.info["OnePickPlaceId"] == "anmok-beach"


@pytest.mark.parametrize(("ratio", "expected"), [("1:1", 1.0), ("4:5", 0.8), ("9:16", 0.5625)])
def test_all_supported_aspect_ratios(client, ratio, expected):
    job_id = _submit(client, ratio=ratio, idempotencyKey=f"ratio-{ratio}").json()["providerJobId"]
    final = _poll_until_terminal(client, job_id)
    assert final["status"] == JobStatus.DONE.value, final.get("error")

    content = client.get(f"/v1/generations/{job_id}/result").content
    with Image.open(io.BytesIO(content)) as image:
        assert round(image.width / image.height, 3) == round(expected, 3)


def test_result_is_not_available_before_completion(client):
    job_id = _submit(client).json()["providerJobId"]
    response = client.get(f"/v1/generations/{job_id}/result")

    # 완료 전이면 409, 이미 끝났다면 200. 둘 다 정상이다.
    assert response.status_code in (200, 409)
    if response.status_code == 409:
        assert response.json()["error"]["code"] == "JOB_NOT_READY"


def test_unknown_job_returns_404(client):
    response = client.get("/v1/generations/does-not-exist")

    assert response.status_code == 404
    assert response.json()["error"] == {
        "code": "JOB_NOT_FOUND",
        "message": "생성 작업을 찾을 수 없습니다.",
        "retryable": False,
    }


def test_identical_request_is_deduplicated(client):
    """검토 총평 §2-7: 같은 입력으로 반복 요청해도 새로 생성하지 않는다."""
    first = _submit(client).json()["providerJobId"]
    second = _submit(client).json()["providerJobId"]

    assert first == second


def test_explicit_idempotency_key_separates_jobs(client):
    first = _submit(client, idempotencyKey="try-1").json()["providerJobId"]
    second = _submit(client, idempotencyKey="try-2").json()["providerJobId"]

    assert first != second


def test_missing_place_id_is_rejected(client):
    files = {"photo": ("photo.jpg", make_image_bytes(), "image/jpeg")}
    response = client.post("/v1/generations", files=files, data={"onePickPlaceId": "   "})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_unsupported_aspect_ratio_is_rejected(client):
    response = _submit(client, ratio="16:9")

    assert response.status_code == 422


def test_cancel_marks_job_and_is_idempotent(client):
    job_id = _submit(client).json()["providerJobId"]

    first = client.post(f"/v1/generations/{job_id}/cancel")
    assert first.status_code == 200

    second = client.post(f"/v1/generations/{job_id}/cancel")
    assert second.status_code == 200


def test_daily_budget_blocks_further_generation(client, monkeypatch):
    from app.api.deps import get_runtime

    monkeypatch.setattr(get_runtime().settings, "daily_generation_budget", 1)

    assert _submit(client, idempotencyKey="budget-1").status_code == 202
    blocked = _submit(client, idempotencyKey="budget-2")

    assert blocked.status_code == 429
    payload = blocked.json()["error"]
    assert payload["code"] == "BUDGET_EXCEEDED"
    # 예산 초과는 재시도해도 소용없다.
    assert payload["retryable"] is False


def test_rate_limit_blocks_burst_from_same_session(client, monkeypatch):
    from app.api.deps import get_runtime

    monkeypatch.setattr(get_runtime().settings, "rate_limit_per_session_per_hour", 1)

    assert _submit(client, idempotencyKey="rate-1", sessionId="s1").status_code == 202
    blocked = _submit(client, idempotencyKey="rate-2", sessionId="s1")

    assert blocked.status_code == 429
    payload = blocked.json()["error"]
    assert payload["code"] == "RATE_LIMITED"
    # 일시적 제한이므로 재시도 가능으로 표시된다.
    assert payload["retryable"] is True


def test_input_photo_is_deleted_after_job_completes(client):
    """요구사항 B5: 원본 사진과 배경 이미지는 Job이 끝나면 즉시 지운다."""
    from app.api.deps import get_runtime

    job_id = _submit(client).json()["providerJobId"]
    _poll_until_terminal(client, job_id)

    record = get_runtime().store.get(job_id)
    assert record is not None
    assert record.input_key is None
    assert record.background_key is None


def test_api_key_header_is_required_on_meta(client):
    client.headers.pop("X-API-Key", None)
    assert client.get("/v1/meta").status_code == 401

    client.headers.update({"X-API-Key": TEST_API_KEY})
    assert client.get("/v1/meta").status_code == 200


# ── 배경 이미지 해석 (백엔드 Place/PlaceImage 연동) ──────────────
def test_uploaded_background_file_is_used_when_provided(client):
    """백엔드가 Place.thumbnailUrl에서 가져온 실제 사진을 forwarding하는 경로."""
    files = {
        "photo": ("photo.jpg", make_image_bytes(), "image/jpeg"),
        "background": (
            "bg.jpg",
            make_image_bytes(width=800, height=600, color=(10, 200, 10)),
            "image/jpeg",
        ),
    }
    data = {"onePickPlaceId": "9c1d4f2e-0000-0000-0000-000000000000", "aspectRatio": "1:1"}

    created = client.post("/v1/generations", files=files, data=data)
    assert created.status_code == 202

    job_id = created.json()["providerJobId"]
    final = _poll_until_terminal(client, job_id)
    assert final["status"] == JobStatus.DONE.value, final.get("error")


def test_dev_catalog_ids_do_not_match_backend_place_uuids(client):
    """개발 카탈로그(anmok-beach 등)는 실제 Place UUID와 매칭되지 않지만,
    mock provider에서는 플레이스홀더로 대체되어 정상 처리돼야 한다."""
    job_id = _submit(client, place="anmok-beach", idempotencyKey="dev-catalog-miss").json()[
        "providerJobId"
    ]
    final = _poll_until_terminal(client, job_id)

    assert final["status"] == JobStatus.DONE.value, final.get("error")


def test_non_mock_provider_requires_a_real_background(client, monkeypatch):
    """AI_PROVIDER=gemini 같은 실 프로바이더에서는 배경 없이 조용히 넘어가면 안 된다."""
    from app.api.deps import get_runtime

    monkeypatch.setattr(get_runtime().provider, "name", "gemini")

    response = _submit(client, idempotencyKey="no-background-real-provider")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "BACKGROUND_REQUIRED"


def test_non_mock_provider_succeeds_when_background_is_uploaded(client, monkeypatch):
    from app.api.deps import get_runtime

    monkeypatch.setattr(get_runtime().provider, "name", "gemini")

    files = {
        "photo": ("photo.jpg", make_image_bytes(), "image/jpeg"),
        "background": ("bg.jpg", make_image_bytes(width=800, height=600), "image/jpeg"),
    }
    data = {"onePickPlaceId": "real-place-uuid", "idempotencyKey": "gemini-with-bg"}

    response = client.post("/v1/generations", files=files, data=data)

    assert response.status_code == 202


def test_backend_supplied_place_fields_are_stored_on_the_job(client):
    """백엔드가 보낸 Place.name/region/description이 프롬프트 힌트로 저장돼야 한다."""
    from app.api.deps import get_runtime

    files = {"photo": ("photo.jpg", make_image_bytes(), "image/jpeg")}
    data = {
        "onePickPlaceId": "real-place-uuid",
        "placeName": "안목해변",
        "placeRegion": "강원특별자치도 강릉시",
        "placeDescription": "동해 바다와 백사장이 있는 해변",
        "idempotencyKey": "place-fields-test",
    }

    job_id = client.post("/v1/generations", files=files, data=data).json()["providerJobId"]

    record = get_runtime().store.get(job_id)
    assert record is not None
    assert record.place_name == "안목해변"
    assert record.place_region == "강원특별자치도 강릉시"
    assert record.place_description == "동해 바다와 백사장이 있는 해변"
