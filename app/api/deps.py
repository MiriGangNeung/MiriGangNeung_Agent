"""런타임 싱글턴 배선.

앱 기동 시 한 번 구성하고 라우트에서 꺼내 쓴다. 테스트는 `configure()`를 직접
호출해 mock provider와 인메모리 store로 갈아끼울 수 있다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.core.config import Settings, get_settings
from app.jobs.runner import GenerationRunner
from app.jobs.store import JobStore, build_job_store
from app.providers.base import ImageCompositionProvider
from app.storage.temp_store import TempImageStore

logger = logging.getLogger(__name__)


@dataclass
class Runtime:
    settings: Settings
    store: JobStore
    images: TempImageStore
    provider: ImageCompositionProvider
    runner: GenerationRunner


_runtime: Runtime | None = None


def build_provider(settings: Settings) -> ImageCompositionProvider:
    name = (settings.ai_provider or "mock").lower()

    if name == "gemini":
        if not settings.google_api_key:
            logger.warning(
                "AI_PROVIDER=gemini 인데 GOOGLE_API_KEY가 비어 있어 mock으로 폴백합니다."
            )
        else:
            from app.providers.gemini import GeminiProvider

            return GeminiProvider(settings)

    from app.providers.mock import MockProvider

    return MockProvider()


def configure(settings: Settings | None = None) -> Runtime:
    global _runtime
    settings = settings or get_settings()

    store = build_job_store(settings.redis_host, settings.redis_port, settings.job_ttl_seconds)
    images = TempImageStore(settings.image_temp_dir, settings.result_ttl_seconds)
    provider = build_provider(settings)
    runner = GenerationRunner(provider, store, images, settings)

    _runtime = Runtime(
        settings=settings,
        store=store,
        images=images,
        provider=provider,
        runner=runner,
    )
    logger.info("런타임 구성 완료 (provider=%s, jobStore=%s).", provider.name, store.name)
    return _runtime


def get_runtime() -> Runtime:
    if _runtime is None:
        return configure()
    return _runtime
