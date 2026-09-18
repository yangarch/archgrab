"""인프로세스 작업 큐.

단일 사용자용이라 Celery·Redis 없이 asyncio 로 충분하다. 추출 엔진 호출은
블로킹이라 asyncio.to_thread 로 넘기고, 스레드에서 올라오는 진행률은
call_soon_threadsafe 로 이벤트 루프에 되돌린다.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from collections import defaultdict
from typing import Any

from app.config import get_settings
from app.core.errors import ErrorCode, ArchGrabError
from app.core.models import JobProgress, JobStatus
from app.core.security import mask_secrets
from app.core.url import ParsedUrl
from app.extractors import registry
from app.extractors.base import ProgressEvent, Selection
from app.jobs import store
from app.media import packager, storage

log = logging.getLogger("archgrab.jobs")

# SSE 로는 최대 4회/초, DB 에는 1회/초만 쓴다.
_EVENT_INTERVAL = 0.25
_DB_INTERVAL = 1.0


class JobManager:
    JobItem = tuple[str, ParsedUrl, Selection, bool]

    def __init__(self) -> None:
        self._queue: asyncio.Queue[JobManager.JobItem] | None = None
        self._workers: list[asyncio.Task[None]] = []
        self._subscribers: defaultdict[str, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)

    # ---- 수명 ------------------------------------------------------------
    async def start(self) -> None:
        # 큐는 이것을 await 하는 이벤트 루프에 묶인다. __init__ 에서 만들어두면
        # 프로세스 안에서 앱을 다시 띄울 때(테스트·재기동) 이전 루프의 큐를 물려받아
        # put 은 되지만 대기 중인 워커가 깨지 않는 교착이 생긴다. 그래서 여기서 만든다.
        queue: asyncio.Queue[JobManager.JobItem] = asyncio.Queue()
        self._queue = queue
        count = max(1, get_settings().max_concurrent_downloads)
        self._workers = [
            asyncio.create_task(self._worker_loop(queue), name=f"archgrab-worker-{i}")
            for i in range(count)
        ]
        log.info("워커 %d개 기동", count)

    async def stop(self) -> None:
        for task in self._workers:
            task.cancel()
        for task in self._workers:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._workers.clear()
        self._subscribers.clear()
        self._queue = None

    # ---- 제출 / 구독 -----------------------------------------------------
    async def submit(
        self, parsed: ParsedUrl, selection: Selection, *, bundle: bool = True
    ) -> str:
        registry.get_extractor(parsed.platform)      # 미지원이면 여기서 즉시 거절
        if self._queue is None:
            raise ArchGrabError(ErrorCode.INTERNAL, "작업 큐가 아직 기동되지 않았습니다.")
        job_id = uuid.uuid4().hex
        await store.create(job_id, parsed.url, parsed.platform)
        await self._queue.put((job_id, parsed, selection, bundle))
        return job_id

    def subscribe(self, job_id: str) -> asyncio.Queue[dict[str, Any]]:
        channel: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=64)
        self._subscribers[job_id].add(channel)
        return channel

    def unsubscribe(self, job_id: str, channel: asyncio.Queue[dict[str, Any]]) -> None:
        listeners = self._subscribers.get(job_id)
        if not listeners:
            return
        listeners.discard(channel)
        if not listeners:
            self._subscribers.pop(job_id, None)

    def _publish(self, job_id: str, payload: dict[str, Any]) -> None:
        for channel in list(self._subscribers.get(job_id, ())):
            try:
                channel.put_nowait(payload)
            except asyncio.QueueFull:
                # 느린 구독자 때문에 워커가 막히면 안 된다 — 가장 오래된 걸 버린다.
                with contextlib.suppress(asyncio.QueueEmpty):
                    channel.get_nowait()
                with contextlib.suppress(asyncio.QueueFull):
                    channel.put_nowait(payload)

    async def _publish_state(self, job_id: str) -> None:
        job = await store.get(job_id)
        if job is not None:
            self._publish(job_id, {"type": "state", "job": job.model_dump(mode="json")})

    # ---- 실행 ------------------------------------------------------------
    async def _worker_loop(self, queue: asyncio.Queue[JobItem]) -> None:
        while True:
            job_id, parsed, selection, bundle = await queue.get()
            try:
                await self._run(job_id, parsed, selection, bundle=bundle)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("작업 %s 처리 중 예외", job_id)
                await self._fail(job_id, ArchGrabError(ErrorCode.INTERNAL))
            finally:
                queue.task_done()

    async def _run(
        self, job_id: str, parsed: ParsedUrl, selection: Selection, *, bundle: bool = True
    ) -> None:
        await store.update(job_id, status=JobStatus.DOWNLOADING)
        await self._publish_state(job_id)

        extractor = registry.get_extractor(parsed.platform)
        dest = storage.job_dir(job_id)
        loop = asyncio.get_running_loop()
        state = {"event": 0.0, "db": 0.0}

        def on_progress(event: ProgressEvent) -> None:
            """워커 스레드에서 호출된다 — 루프로 되돌려야 안전하다."""
            now = time.monotonic()
            if now - state["event"] < _EVENT_INTERVAL:
                return
            state["event"] = now
            snapshot = JobProgress(
                done_bytes=event.done_bytes,
                total_bytes=event.total_bytes,
                percent=_percent(event),
                current=event.current,
                index=event.index,
                count=event.count,
            )
            loop.call_soon_threadsafe(self._on_progress, job_id, snapshot, state, now)

        try:
            paths = await asyncio.to_thread(
                extractor.download, parsed, selection, dest, on_progress
            )
        except ArchGrabError as exc:
            await self._fail(job_id, exc)
            return

        if not paths:
            await self._fail(job_id, ArchGrabError(ErrorCode.ENGINE_FAILED, "받은 파일이 없습니다."))
            return

        await store.update(job_id, status=JobStatus.PACKAGING)
        await self._publish_state(job_id)

        # 낱개로 저장할 작업이면 zip 을 만들지 않는다 — 쓰이지 않는데 TTL 동안
        # 디스크를 두 배로 잡는다.
        if bundle and len(paths) > 1:
            base = f"{parsed.platform.value}_{parsed.username or parsed.key}"
            paths = [*paths, await asyncio.to_thread(packager.make_zip, dest, base, paths)]

        files = await asyncio.to_thread(packager.to_job_files, job_id, paths)
        now = time.time()
        await store.update(
            job_id,
            status=JobStatus.DONE,
            files=files,
            title=files[0].name if files else None,
            progress=JobProgress(percent=100.0, count=len(files), index=len(files)),
            finished_at=now,
            expires_at=now + get_settings().file_ttl_seconds,
        )
        await self._publish_state(job_id)

    def _on_progress(
        self, job_id: str, snapshot: JobProgress, state: dict[str, float], now: float
    ) -> None:
        self._publish(job_id, {"type": "progress", "progress": snapshot.model_dump(mode="json")})
        if now - state["db"] >= _DB_INTERVAL:
            state["db"] = now
            asyncio.create_task(store.update(job_id, progress=snapshot))  # noqa: RUF006

    async def _fail(self, job_id: str, error: ArchGrabError) -> None:
        log.info("작업 %s 실패: %s %s", job_id, error.code, mask_secrets(error.detail or ""))
        await store.update(
            job_id,
            status=JobStatus.ERROR,
            error_code=error.code.value,
            error_message=error.message,
            finished_at=time.time(),
        )
        await self._publish_state(job_id)


def _percent(event: ProgressEvent) -> float:
    """여러 파일을 받을 때는 '완료한 파일 + 현재 파일 진행률' 로 계산한다."""
    if event.count > 1:
        completed = max(0, event.index - 1)
        within = (
            event.done_bytes / event.total_bytes
            if event.total_bytes
            else 0.0
        )
        return round(min(100.0, (completed + within) / event.count * 100), 1)
    if event.total_bytes:
        return round(min(100.0, event.done_bytes / event.total_bytes * 100), 1)
    return 0.0


manager = JobManager()
