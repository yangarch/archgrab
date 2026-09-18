"""작업 상태 저장 — SQLite. 단일 사용자라 이 이상은 필요 없다."""

from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any

import aiosqlite

from app.config import get_settings
from app.core.models import Job, JobFile, JobProgress, JobStatus
from app.core.url import Platform

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id            TEXT PRIMARY KEY,
    status        TEXT NOT NULL,
    url           TEXT NOT NULL,
    platform      TEXT,
    title         TEXT,
    progress      TEXT NOT NULL DEFAULT '{}',
    files         TEXT NOT NULL DEFAULT '[]',
    error_code    TEXT,
    error_message TEXT,
    created_at    REAL NOT NULL,
    finished_at   REAL,
    expires_at    REAL
);
CREATE INDEX IF NOT EXISTS jobs_created_at ON jobs (created_at DESC);
CREATE INDEX IF NOT EXISTS jobs_expires_at ON jobs (expires_at);
"""


async def _connect() -> aiosqlite.Connection:
    settings = get_settings()
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = await aiosqlite.connect(settings.db_path)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA journal_mode=WAL")
    return conn


async def init_db() -> None:
    conn = await _connect()
    try:
        await conn.executescript(_SCHEMA)
        await conn.commit()
    finally:
        await conn.close()


def _to_job(row: aiosqlite.Row) -> Job:
    return Job(
        id=row["id"],
        status=JobStatus(row["status"]),
        url=row["url"],
        platform=Platform(row["platform"]) if row["platform"] else None,
        title=row["title"],
        progress=JobProgress(**json.loads(row["progress"] or "{}")),
        files=[JobFile(**f) for f in json.loads(row["files"] or "[]")],
        error_code=row["error_code"],
        error_message=row["error_message"],
        created_at=datetime.fromtimestamp(row["created_at"]),
        finished_at=(
            datetime.fromtimestamp(row["finished_at"]) if row["finished_at"] else None
        ),
        expires_at=datetime.fromtimestamp(row["expires_at"]) if row["expires_at"] else None,
    )


async def create(job_id: str, url: str, platform: Platform | None) -> Job:
    now = time.time()
    conn = await _connect()
    try:
        await conn.execute(
            "INSERT INTO jobs (id, status, url, platform, created_at) VALUES (?, ?, ?, ?, ?)",
            (job_id, JobStatus.QUEUED.value, url, platform.value if platform else None, now),
        )
        await conn.commit()
    finally:
        await conn.close()
    job = await get(job_id)
    assert job is not None
    return job


_JSON_FIELDS = {"progress", "files"}
_ALLOWED = {
    "status", "title", "progress", "files",
    "error_code", "error_message", "finished_at", "expires_at",
}


async def update(job_id: str, **fields: Any) -> None:
    payload: dict[str, Any] = {}
    for key, value in fields.items():
        if key not in _ALLOWED:
            raise ValueError(f"갱신할 수 없는 필드: {key}")
        if key in _JSON_FIELDS:
            if hasattr(value, "model_dump"):
                value = value.model_dump(mode="json")
            elif isinstance(value, list):
                value = [v.model_dump(mode="json") if hasattr(v, "model_dump") else v for v in value]
            value = json.dumps(value, ensure_ascii=False)
        elif hasattr(value, "value"):
            value = value.value
        payload[key] = value

    if not payload:
        return

    assignments = ", ".join(f"{key} = ?" for key in payload)
    conn = await _connect()
    try:
        await conn.execute(
            f"UPDATE jobs SET {assignments} WHERE id = ?",  # noqa: S608 — 키는 화이트리스트
            (*payload.values(), job_id),
        )
        await conn.commit()
    finally:
        await conn.close()


async def get(job_id: str) -> Job | None:
    conn = await _connect()
    try:
        async with conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)) as cursor:
            row = await cursor.fetchone()
    finally:
        await conn.close()
    return _to_job(row) if row else None


async def list_recent(limit: int = 30) -> list[Job]:
    conn = await _connect()
    try:
        async with conn.execute(
            "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
        ) as cursor:
            rows = await cursor.fetchall()
    finally:
        await conn.close()
    return [_to_job(row) for row in rows]


async def expired(now: float | None = None) -> list[str]:
    cutoff = now if now is not None else time.time()
    conn = await _connect()
    try:
        async with conn.execute(
            "SELECT id FROM jobs WHERE expires_at IS NOT NULL AND expires_at < ?", (cutoff,)
        ) as cursor:
            rows = await cursor.fetchall()
    finally:
        await conn.close()
    return [row["id"] for row in rows]


async def delete(job_id: str) -> None:
    conn = await _connect()
    try:
        await conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        await conn.commit()
    finally:
        await conn.close()
