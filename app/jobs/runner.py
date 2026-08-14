"""Job 실행기.

상태 전이:
    QUEUED -> ANALYZING -> COMPOSITING -> QUALITY_CHECK -> DONE | FAILED

사진 유효성 검사(B3/B4)와 전처리(B5)는 **POST 핸들러에서 동기로** 처리한다.
요구사항 B4가 "분석 전에 차단하고 재업로드 방법을 안내"하도록 요구하므로, 잘못된
사진은 Job을 만들지 않고 즉시 4xx로 돌려주는 편이 맞다. 따라서 여기 ANALYZING
단계는 스타일 분석(B6)만 담당한다.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from app.core.config import Settings
from app.core.errors import SAFETY_ERROR_CODES, AiServiceError
from app.jobs.store import JobRecord, JobStore
from app.pipeline import safety, style
from app.pipeline.compose import compose_with_retry
from app.pipeline.finalize import finalize_image
from app.pipeline.prompt import build_composition_prompt
from app.places.backgrounds import resolve_place_context
from app.providers.base import CompositionRequest, ImageCompositionProvider
from app.schemas.generation import JobStatus, SafetyStatus
from app.storage.temp_store import TempImageStore

logger = logging.getLogger(__name__)


class GenerationRunner:
    def __init__(
        self,
        provider: ImageCompositionProvider,
        store: JobStore,
        images: TempImageStore,
        settings: Settings,
    ):
        self.provider = provider
        self.store = store
        self.images = images
        self.settings = settings
        self._tasks: set[asyncio.Task] = set()

    def schedule(self, record: JobRecord) -> None:
        task = asyncio.create_task(self._run(record.provider_job_id))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def drain(self) -> None:
        """종료 시 진행 중인 Job을 정리한다."""
        for task in list(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

    async def _run(self, job_id: str) -> None:
        record = self.store.get(job_id)
        if record is None:
            logger.warning("실행할 Job을 찾지 못했습니다.")
            return

        try:
            await self._execute(record)
        except AiServiceError as exc:
            self._fail(record, exc)
        except asyncio.CancelledError:
            logger.info("Job이 취소되었습니다.")
            raise
        except Exception:  # noqa: BLE001
            logger.exception("Job 처리 중 예상치 못한 오류가 발생했습니다.")
            self._fail(record, AiServiceError("INTERNAL_ERROR"))
        finally:
            # 개인정보: 원본 입력은 Job이 끝나는 즉시 지운다 (요구사항 B5).
            latest = self.store.get(job_id) or record
            changed = False
            if latest.input_key:
                self.images.delete_input(latest.input_key)
                latest.input_key = None
                changed = True
            if latest.background_key:
                self.images.delete_input(latest.background_key)
                latest.background_key = None
                changed = True
            if changed:
                self.store.save(latest)

    async def _execute(self, record: JobRecord) -> None:
        if record.input_key is None:
            raise AiServiceError("INTERNAL_ERROR", "입력 이미지를 찾을 수 없습니다.")

        person_image = self.images.read_input(record.input_key)
        person_mime = "image/png"  # 전처리 단계에서 PNG로 정규화된다

        # ── ANALYZING: 스타일 분석 (B6) ──────────────────────
        self._advance(record, JobStatus.ANALYZING)
        record.style_tags = await style.analyze_style(self.provider, person_image, person_mime)
        self.store.save(record)
        self._raise_if_cancelled(record)

        # ── COMPOSITING: 합성 (E1~E4, E8) ────────────────────
        self._advance(record, JobStatus.COMPOSITING)
        if record.background_key is None:
            # 제출 시점에 항상 채워져야 한다 (routes_generation.py). 여기 도달하면 버그다.
            raise AiServiceError("INTERNAL_ERROR", "배경 이미지를 찾을 수 없습니다.")
        background_image = self.images.read_input(record.background_key)
        background_mime = "image/png"

        place = resolve_place_context(
            record.one_pick_place_id,
            place_name=record.place_name,
            place_region=record.place_region,
            place_description=record.place_description,
        )
        prompt = build_composition_prompt(place, record.aspect_ratio, record.style_tags)

        output, attempts = await compose_with_retry(
            self.provider,
            CompositionRequest(
                person_image=person_image,
                person_mime=person_mime,
                background_image=background_image,
                background_mime=background_mime,
                prompt=prompt,
                aspect_ratio=record.aspect_ratio,
            ),
            timeout_seconds=self.settings.provider_timeout_seconds,
            max_retries=self.settings.provider_max_retries,
        )
        record.attempts = attempts
        record.estimated_cost_usd = output.estimated_cost_usd
        self.store.save(record)
        self._raise_if_cancelled(record)

        # ── QUALITY_CHECK: 안전성·품질 (E5) ──────────────────
        self._advance(record, JobStatus.QUALITY_CHECK)
        safety_status, reason = await safety.check_output(self.provider, output.image, output.mime)
        record.safety_status = safety_status
        record.safety_reason_code = reason
        self.store.save(record)
        self._raise_if_cancelled(record)

        # ── DONE: 마감 (E4, E6, E9) ──────────────────────────
        final_bytes, width, height = finalize_image(
            output.image,
            record.aspect_ratio,
            provider=self.provider.name,
            model=self.provider.image_model,
            prompt_version=record.prompt_version,
            place_id=record.one_pick_place_id,
        )
        record.result_key = self.images.save_result(final_bytes)
        record.result_width = width
        record.result_height = height
        record.status = JobStatus.DONE
        record.completed_at = _now_iso()
        self.store.save(record)
        logger.info("Job 완료 (attempts=%d, %dx%d).", attempts, width, height)

    def _advance(self, record: JobRecord, status: JobStatus) -> None:
        record.status = status
        self.store.save(record)

    def _raise_if_cancelled(self, record: JobRecord) -> None:
        latest = self.store.get(record.provider_job_id)
        if latest and latest.cancelled:
            raise AiServiceError("INVALID_REQUEST", "요청이 취소되었습니다.")

    def _fail(self, record: JobRecord, error: AiServiceError) -> None:
        latest = self.store.get(record.provider_job_id) or record
        latest.status = JobStatus.FAILED
        latest.error_code = error.code
        latest.error_message = error.message
        latest.error_retryable = error.retryable
        latest.completed_at = _now_iso()
        if error.code in SAFETY_ERROR_CODES:
            latest.safety_status = SafetyStatus.REJECTED
            latest.safety_reason_code = error.code
        self.store.save(latest)
        logger.info("Job 실패 (code=%s, retryable=%s).", error.code, error.retryable)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
