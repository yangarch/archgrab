"""TTL 이 지난 작업 파일을 지운다. 없으면 디스크가 무한히 찬다."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import shutil

from app.config import get_settings
from app.jobs import store

log = logging.getLogger("archgrab.reaper")

SWEEP_INTERVAL = 300
_JOB_DIR = re.compile(r"^[0-9a-f]{32}$")


async def sweep_once() -> int:
    settings = get_settings()
    removed = 0

    for job_id in await store.expired():
        shutil.rmtree(settings.data_dir / job_id, ignore_errors=True)
        await store.delete(job_id)
        removed += 1

    # DB 에 없는 고아 디렉터리도 정리한다 (예: 크래시로 레코드가 유실된 경우)
    known = {job.id for job in await store.list_recent(limit=500)}
    if settings.data_dir.is_dir():
        for path in settings.data_dir.iterdir():
            if path.is_dir() and _JOB_DIR.match(path.name) and path.name not in known:
                shutil.rmtree(path, ignore_errors=True)
                removed += 1

    if removed:
        log.info("%d개 작업 정리", removed)
    return removed


async def run_forever() -> None:
    while True:
        try:
            await sweep_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("정리 중 오류")
        await asyncio.sleep(SWEEP_INTERVAL)


def start() -> asyncio.Task[None]:
    return asyncio.create_task(run_forever(), name="archgrab-reaper")


async def stop(task: asyncio.Task[None]) -> None:
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
