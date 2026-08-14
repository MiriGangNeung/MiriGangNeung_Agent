"""임시 이미지 저장소.

개인정보 정책 (요구사항 A4/B5, 검토 총평 §4):
- 파일명은 무작위화한다. 사용자가 올린 원본 파일명을 디스크에도 로그에도 남기지 않는다.
- 입력 원본은 Job이 끝나는 즉시 삭제한다.
- 결과는 RESULT_TTL_SECONDS 후 만료되며 정리 루프가 지운다.
"""

from __future__ import annotations

import logging
import time
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

INPUT_SUBDIR = "input"
RESULT_SUBDIR = "result"


class TempImageStore:
    def __init__(self, base_dir: Path, result_ttl_seconds: int):
        self.base_dir = Path(base_dir)
        self.result_ttl_seconds = result_ttl_seconds
        for sub in (INPUT_SUBDIR, RESULT_SUBDIR):
            (self.base_dir / sub).mkdir(parents=True, exist_ok=True)

    def _path(self, subdir: str, key: str) -> Path:
        # key는 이 클래스가 생성한 무작위 이름만 허용한다 (경로 조작 차단).
        safe = Path(key).name
        return self.base_dir / subdir / safe

    def save_input(self, data: bytes, suffix: str = ".bin") -> str:
        key = f"{uuid.uuid4().hex}{suffix}"
        self._path(INPUT_SUBDIR, key).write_bytes(data)
        return key

    def save_result(self, data: bytes, suffix: str = ".png") -> str:
        key = f"{uuid.uuid4().hex}{suffix}"
        self._path(RESULT_SUBDIR, key).write_bytes(data)
        return key

    def read_input(self, key: str) -> bytes:
        return self._path(INPUT_SUBDIR, key).read_bytes()

    def read_result(self, key: str) -> bytes:
        return self._path(RESULT_SUBDIR, key).read_bytes()

    def result_exists(self, key: str) -> bool:
        return self._path(RESULT_SUBDIR, key).is_file()

    def delete_input(self, key: str) -> None:
        self._path(INPUT_SUBDIR, key).unlink(missing_ok=True)

    def delete_result(self, key: str) -> None:
        self._path(RESULT_SUBDIR, key).unlink(missing_ok=True)

    def purge_expired(self) -> int:
        """TTL이 지난 결과 파일과 남아 있는 입력 파일을 지운다."""
        removed = 0
        cutoff = time.time() - self.result_ttl_seconds
        for subdir in (INPUT_SUBDIR, RESULT_SUBDIR):
            directory = self.base_dir / subdir
            if not directory.is_dir():
                continue
            for path in directory.iterdir():
                if not path.is_file():
                    continue
                try:
                    if path.stat().st_mtime < cutoff:
                        path.unlink(missing_ok=True)
                        removed += 1
                except OSError:
                    logger.warning("임시 파일 정리 실패 (subdir=%s)", subdir)
        if removed:
            logger.info("만료된 임시 이미지 %d건을 삭제했습니다.", removed)
        return removed
