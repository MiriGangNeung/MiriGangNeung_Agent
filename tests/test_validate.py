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


def _staged_detector(monkeypatch, *stages: list[FaceBox]):
    """호출 순서대로 다른 결과를 돌려주는 detect_faces 스텁.

    `_crop_to_primary`가 잘라낸 뒤 한 번 더 검출하므로, 원본과 크롭 후를 나눠 준다.
    """
    calls = iter(stages)
    last: list[list[FaceBox]] = [stages[-1]]

    def fake(_matrix):
        return next(calls, last[0])

    monkeypatch.setattr(validate_module, "detect_faces", fake)


def test_crops_to_primary_subject_when_one_face_clearly_dominates(monkeypatch):
    """뒤에 다른 사람이 걸친 셀피는 거부 대신 주 피사체만 잘라 살린다."""
    _staged_detector(
        monkeypatch,
        [FaceBox(100, 100, 200, 200), FaceBox(120, 400, 90, 90)],
        [FaceBox(100, 100, 200, 200)],
    )
    monkeypatch.setattr(validate_module, "_is_face_occluded", lambda *_: False)
    original = make_noise_image_bytes(width=640, height=800)

    report = validate_photo(original, "image/png", **LIMITS)

    assert report.cropped_from_group is True
    assert report.data and report.data != original
    # 두 번째 얼굴(y=400)을 잘라내려면 아래쪽을 400에서 끊는 것이 손실이 가장 적다.
    assert report.height == 400
    assert report.width == 640


def test_keeps_rejecting_group_photos_without_a_clear_subject(monkeypatch):
    """비슷한 크기로 나란히 선 사진은 누가 주인공인지 알 수 없어 그대로 거부한다."""
    _staged_detector(
        monkeypatch,
        [FaceBox(50, 100, 200, 200), FaceBox(350, 100, 190, 190)],
    )
    _expect("MULTIPLE_PERSONS", make_noise_image_bytes())


def test_rejects_when_faces_overlap_and_cannot_be_separated(monkeypatch):
    """얼굴이 겹쳐 있으면 어느 방향으로 잘라도 분리되지 않으므로 거부한다."""
    _staged_detector(
        monkeypatch,
        [FaceBox(100, 100, 300, 300), FaceBox(150, 150, 100, 100)],
    )
    _expect("MULTIPLE_PERSONS", make_noise_image_bytes())


def test_single_face_photo_is_not_cropped(monkeypatch):
    _staged_detector(monkeypatch, [FaceBox(100, 100, 200, 200)])
    monkeypatch.setattr(validate_module, "_is_face_occluded", lambda *_: False)
    original = make_noise_image_bytes()

    report = validate_photo(original, "image/png", **LIMITS)

    assert report.cropped_from_group is False
    assert report.data == original


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
