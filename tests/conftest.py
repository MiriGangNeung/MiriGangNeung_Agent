from __future__ import annotations

import io

import numpy as np
import pytest
from PIL import Image

TEST_API_KEY = "test-key"


@pytest.fixture(autouse=True)
def _test_env(tmp_path, monkeypatch):
    """모든 테스트를 격리된 임시 디렉터리 + mock provider + 인메모리 store로 돌린다."""
    monkeypatch.setenv("AI_API_KEY", TEST_API_KEY)
    monkeypatch.setenv("AI_PROVIDER", "mock")
    monkeypatch.setenv("REDIS_HOST", "")
    monkeypatch.setenv("IMAGE_TEMP_DIR", str(tmp_path / "images"))
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    monkeypatch.setenv("DAILY_GENERATION_BUDGET", "500")
    monkeypatch.setenv("RATE_LIMIT_PER_SESSION_PER_HOUR", "100")

    from app.core.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client(monkeypatch):
    from fastapi.testclient import TestClient

    # Mock 합성 지연은 테스트에서 필요 없다.
    monkeypatch.setattr("app.providers.mock.MOCK_COMPOSE_DELAY_SECONDS", 0.0)

    from app.main import create_app

    with TestClient(create_app()) as test_client:
        test_client.headers.update({"X-API-Key": TEST_API_KEY})
        yield test_client


def make_image_bytes(
    width: int = 640, height: int = 800, fmt: str = "JPEG", color=(120, 160, 200)
) -> bytes:
    """테스트용 단색 이미지. 얼굴이 없으므로 검출기는 0명을 반환한다."""
    image = Image.new("RGB", (width, height), color)
    buffer = io.BytesIO()
    image.save(buffer, format=fmt)
    return buffer.getvalue()


def make_noise_image_bytes(width: int = 640, height: int = 800) -> bytes:
    """Laplacian 분산이 높은(선명한) 이미지."""
    array = np.random.default_rng(7).integers(0, 256, (height, width, 3), dtype=np.uint8)
    buffer = io.BytesIO()
    Image.fromarray(array).save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def photo_bytes() -> bytes:
    return make_image_bytes()
