"""환경변수 기반 설정. .env.example이 전체 목록의 기준 문서다."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    # 서비스
    ai_api_key: str = ""
    port: int = 8100
    log_level: str = "INFO"

    # Provider
    ai_provider: str = "mock"
    google_api_key: str = ""
    gemini_image_model: str = "gemini-3.1-flash-image"
    gemini_vision_model: str = "gemini-3.1-flash-lite"
    provider_timeout_seconds: float = 120.0
    provider_max_retries: int = 2

    # Job store
    redis_host: str = ""
    redis_port: int = 6379
    job_ttl_seconds: int = 86400

    # 이미지 / 개인정보
    image_temp_dir: Path = Path("/tmp/mirigangneung-ai")
    max_upload_bytes: int = 10 * 1024 * 1024
    max_image_pixels: int = 40_000_000
    result_ttl_seconds: int = 86400

    # 비용 제어
    daily_generation_budget: int = 500
    rate_limit_per_session_per_hour: int = 10

    # 얼굴 검출 (B3/B4) — 비우면 OpenCV 번들 Haar cascade로 폴백
    face_model_path: str = ""
    # 신원 유사도 판정용 SFace 모델 (opencv_zoo, Apache-2.0). 비어 있거나 파일이 없으면
    # 판정을 생략하고 1회 생성으로 동작한다 — 필수 경로가 아니다.
    face_recognition_model_path: str = "models/face_recognition_sface_2021dec.onnx"

    # 얼굴 신원 유사도 (SFace 코사인). 두 값을 나눠 둔 이유:
    #  - target: 이 값에 못 미치면 "더 잘 뽑아보자"고 재생성한다. 높게 잡아도
    #    사용자에게 보이는 건 없고 비용만 든다.
    #  - warn_below: 재생성을 다 쓰고도 이 값에 못 미칠 때만 경고를 단다. 사용자를
    #    귀찮게 하는 선이라 널널하게 잡는다.
    # 실측 보정(2026-09-02, 라벨 4장 + 기존 결과 23장): 사람 눈으로 "다른 사람"이라고
    # 판정한 것이 0.269, "같은 사람"이 0.549~0.571이었다. SFace 문서 기준값은 0.363.
    face_similarity_target: float = 0.45
    face_similarity_warn_below: float = 0.30
    # 얼굴 유사도가 target에 못 미칠 때 합성을 몇 번까지 다시 할지 (첫 시도 포함).
    face_regenerate_max_attempts: int = 3
    # 업로드 사진에서 얼굴이 화면 높이의 이 비율 미만이면 얼굴 참조 이미지를 함께 넘긴다.
    # 거부 조건이 아니라 "도움을 더 줄까"를 정하는 값이라 널널하게 잡는다.
    face_ratio_assist_below: float = 0.5
    # 얼굴 참조 이미지 기능 자체를 끄는 스위치 (효과 측정·롤백용).
    face_reference_enabled: bool = True

    @property
    def auth_enabled(self) -> bool:
        """AI_API_KEY가 비어 있으면 로컬 개발로 간주하고 인증을 끈다."""
        return bool(self.ai_api_key)

    @property
    def prompts_dir(self) -> Path:
        return REPO_ROOT / "prompts"

    @property
    def backgrounds_dir(self) -> Path:
        return REPO_ROOT / "assets" / "backgrounds"

    @property
    def places_dir(self) -> Path:
        return REPO_ROOT / "assets" / "places"

    @property
    def resolved_face_model_path(self) -> str:
        """상대경로면 리포 루트 기준으로 해석한다 (cwd가 어디든 동작하도록)."""
        return _resolve(self.face_model_path)

    @property
    def resolved_face_recognition_model_path(self) -> str:
        return _resolve(self.face_recognition_model_path)


@lru_cache
def get_settings() -> Settings:
    return Settings()


def _resolve(raw: str) -> str:
    """설정의 모델 경로를 절대경로로. 비어 있으면 빈 문자열(=사용 안 함)."""
    if not raw:
        return ""
    path = Path(raw)
    if not path.is_absolute():
        path = REPO_ROOT / path
    return str(path)
