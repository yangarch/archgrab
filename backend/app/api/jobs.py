"""다운로드 작업 생성·조회와 SSE 진행률 스트림."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.auth import AuthRequired
from app.core.errors import ErrorCode, ArchGrabError
from app.core.models import Job, JobCreate, JobStatus
from app.core.url import parse_url
from app.extractors.base import Selection
from app.jobs import store
from app.jobs.queue import manager

router = APIRouter(prefix="/jobs", tags=["jobs"], dependencies=[AuthRequired])

TERMINAL = {JobStatus.DONE, JobStatus.ERROR, JobStatus.CANCELED}
KEEPALIVE_SECONDS = 15


class JobCreated(BaseModel):
    job_id: str


@router.post("", response_model=JobCreated)
async def create_job(payload: JobCreate) -> JobCreated:
    parsed = parse_url(payload.url)
    selection = Selection(
        item_ids=frozenset(payload.item_ids) if payload.item_ids else None,
        format_ids=payload.format_ids or {},
        audio_only=payload.audio_only,
    )
    return JobCreated(job_id=await manager.submit(parsed, selection, bundle=payload.bundle))


@router.get("", response_model=list[Job])
async def list_jobs(limit: int = 30) -> list[Job]:
    return await store.list_recent(limit=max(1, min(limit, 100)))


@router.get("/{job_id}", response_model=Job)
async def get_job(job_id: str) -> Job:
    job = await store.get(job_id)
    if job is None:
        raise ArchGrabError(ErrorCode.NOT_FOUND, "작업을 찾을 수 없습니다.")
    return job


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.get("/{job_id}/events")
async def job_events(job_id: str) -> StreamingResponse:
    """EventSource 로 구독. 세션 쿠키가 같은 출처로 실려오므로 인증이 그대로 걸린다."""
    job = await store.get(job_id)
    if job is None:
        raise ArchGrabError(ErrorCode.NOT_FOUND, "작업을 찾을 수 없습니다.")

    async def stream() -> AsyncIterator[str]:
        channel = manager.subscribe(job_id)
        try:
            current = await store.get(job_id)
            if current is None:
                return
            yield _sse("state", {"job": current.model_dump(mode="json")})
            if current.status in TERMINAL:
                return

            while True:
                try:
                    payload = await asyncio.wait_for(channel.get(), timeout=KEEPALIVE_SECONDS)
                except TimeoutError:
                    # 중간 프록시가 조용한 연결을 끊지 않도록 주석 프레임을 흘린다
                    yield ": keep-alive\n\n"
                    continue

                kind = str(payload.get("type", "state"))
                yield _sse(kind, payload)
                if kind == "state" and payload.get("job", {}).get("status") in {
                    s.value for s in TERMINAL
                }:
                    return
        finally:
            manager.unsubscribe(job_id, channel)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",      # nginx 버퍼링 비활성
        },
    )
