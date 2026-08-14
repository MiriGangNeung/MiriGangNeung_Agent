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
    gemini_vision_model: str = "gemini-3.1-flash"
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


@lru_cache
def get_settings() -> Settings:
    return Settings()
