"""사진 유효성 검사 (요구사항 B3, B4)."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image

from app.core.config import Settings
from app.core.errors import AiServiceError
from app.pipeline import validate as validate_module
from app.pipeline.validate import FaceBox, validate_photo
from tests.conftest import make_image_bytes, make_noise_image_bytes

LIMITS = {"max_bytes": 10 * 1024 * 1024, "max_pixels": 40_000_000}


def _expect(code: str, data: bytes, mime: str | None = "image/png", **overrides):
    limits = {**LIMITS, **overrides}
    with pytest.raises(AiServiceError) as excinfo:
        validate_photo(data, mime, **limits)
    assert excinfo.value.code == code
    return excinfo.value


def test_rejects_oversized_file():
    error = _expect("IMAGE_TOO_LARGE", make_image_bytes(), max_bytes=10)
    assert error.http_status == 413
    assert error.retryable is False


def test_rejects_declared_mime_outside_allowlist():
    _expect("INVALID_IMAGE_FORMAT", make_image_bytes(), "image/gif")


def test_rejects_corrupted_bytes():
    _expect("INVALID_IMAGE_FORMAT", b"not an image at all", None)


def test_rejects_file_whose_real_format_is_not_allowed():
    """확장자·MIME이 아니라 실제 디코딩 결과로 판단해야 한다."""
    buffer = io.BytesIO()
    Image.new("RGB", (64, 64), (10, 20, 30)).save(buffer, format="GIF")
    # 호출자가 PNG라고 주장해도 실제 형식이 GIF이므로 거부된다.
    _expect("INVALID_IMAGE_FORMAT", buffer.getvalue(), "image/png")


def test_rejects_animated_image():
    buffer = io.BytesIO()
    # 프레임 색이 거의 같으면 WEBP 인코더가 병합해 버리므로 뚜렷하게 다른 색을 쓴다.
    frames = [Image.new("RGB", (64, 64), c) for c in ((10, 20, 30), (200, 50, 60))]
    frames[0].save(buffer, format="WEBP", save_all=True, append_images=frames[1:], duration=100)
    _expect("INVALID_IMAGE_FORMAT", buffer.getvalue(), "image/webp")


def test_rejects_too_many_pixels():
    _expect("IMAGE_TOO_MANY_PIXELS", make_image_bytes(), max_pixels=100)


def test_rejects_photo_without_person():
    """단색 이미지에는 얼굴이 없으므로 B4에 따라 차단된다."""
    _expect("NO_PERSON_DETECTED", make_image_bytes(fmt="PNG"))


def test_rejects_multiple_persons(monkeypatch):
    monkeypatch.setattr(
        validate_module,
        "detect_faces",
        lambda _: [FaceBox(10, 10, 100, 100), FaceBox(300, 10, 100, 100)],
    )
    _expect("MULTIPLE_PERSONS", make_image_bytes(fmt="PNG"))


def test_rejects_face_too_small_in_frame(monkeypatch):
    monkeypatch.setattr(validate_module, "detect_faces", lambda _: [FaceBox(0, 0, 8, 8)])
    _expect("NO_PERSON_DETECTED", make_image_bytes(fmt="PNG"))


def test_rejects_blurry_face(monkeypatch):
    """단색(=Laplacian 분산 0) 얼굴 영역은 흐린 것으로 판정된다."""
    monkeypatch.setattr(validate_module, "detect_faces", lambda _: [FaceBox(100, 100, 200, 200)])
    _expect("IMAGE_TOO_BLURRY", make_image_bytes(fmt="PNG"))


def test_rejects_occluded_face(monkeypatch):
    """노이즈 이미지는 선명하지만 눈이 검출되지 않으므로 가림으로 판정된다."""
    monkeypatch.setattr(validate_module, "detect_faces", lambda _: [FaceBox(100, 100, 200, 200)])
    _expect("FACE_OCCLUDED", make_noise_image_bytes())


def test_accepts_sharp_unoccluded_face(monkeypatch):
    monkeypatch.setattr(validate_module, "detect_faces", lambda _: [FaceBox(100, 100, 200, 200)])
    monkeypatch.setattr(validate_module, "_is_face_occluded", lambda *_: False)

    report = validate_photo(make_noise_image_bytes(), "image/png", **LIMITS)

    assert report.format == "PNG"
    assert report.sharpness > validate_module.BLUR_VARIANCE_THRESHOLD
    assert report.face.w == 200


# ── 얼굴 검출 모델 경로 해석 (YuNet) ─────────────────────────
def test_resolved_face_model_path_is_empty_when_unset():
    assert Settings(face_model_path="").resolved_face_model_path == ""


def test_resolved_face_model_path_resolves_relative_to_repo_root():
    """리포에 커밋된 YuNet 모델을 cwd와 무관하게 찾을 수 있어야 한다."""
    settings = Settings(face_model_path="models/face_detection_yunet_2023mar.onnx")

    resolved = settings.resolved_face_model_path

    assert resolved.endswith("models/face_detection_yunet_2023mar.onnx")
    assert Path(resolved).is_absolute()


def test_bundled_yunet_model_file_exists_at_the_default_path():
    """`.env.example`의 FACE_MODEL_PATH 기본값이 실제로 커밋된 파일을 가리켜야 한다."""
    settings = Settings(face_model_path="models/face_detection_yunet_2023mar.onnx")

    assert Path(settings.resolved_face_model_path).is_file()
