"""완성된 파일 전달과 썸네일 중계."""

from __future__ import annotations

from collections.abc import AsyncIterator
from urllib.parse import quote

import httpx
from fastapi import APIRouter
from fastapi.responses import FileResponse, StreamingResponse

from app.auth import AuthRequired
from app.config import get_settings
from app.core.errors import ErrorCode, ArchGrabError
from app.media.fetcher import DEFAULT_HEADERS
from app.media.storage import resolve_thumb_token, resolve_token

router = APIRouter(tags=["files"], dependencies=[AuthRequired])

THUMB_MAX_BYTES = 8 * 1024 * 1024


@router.get("/files/{token}")
async def download_file(token: str) -> FileResponse:
    path = resolve_token(token)
    # RFC 5987 — 한글 파일명이 깨지지 않게 filename* 을 함께 준다
    disposition = f"attachment; filename*=UTF-8''{quote(path.name)}"
    return FileResponse(
        path,
        filename=path.name,
        headers={"Content-Disposition": disposition, "Cache-Control": "private, max-age=3600"},
    )


@router.get("/thumb/{token}")
async def thumbnail(token: str) -> StreamingResponse:
    url = resolve_thumb_token(token)
    settings = get_settings()

    client = httpx.AsyncClient(
        follow_redirects=True,
        timeout=httpx.Timeout(10.0, read=20.0),
        headers={**DEFAULT_HEADERS, "Referer": "https://www.instagram.com/"},
        proxy=settings.proxy,
    )

    try:
        request = client.build_request("GET", url)
        response = await client.send(request, stream=True)
    except httpx.HTTPError as exc:
        await client.aclose()
        raise ArchGrabError(ErrorCode.NOT_FOUND, detail=str(exc)) from exc

    if response.status_code >= 400:
        await response.aclose()
        await client.aclose()
        raise ArchGrabError(ErrorCode.NOT_FOUND, detail=f"HTTP {response.status_code}")

    async def stream() -> AsyncIterator[bytes]:
        sent = 0
        try:
            async for chunk in response.aiter_bytes(64 * 1024):
                sent += len(chunk)
                if sent > THUMB_MAX_BYTES:
                    break
                yield chunk
        finally:
            await response.aclose()
            await client.aclose()

    return StreamingResponse(
        stream(),
        media_type=response.headers.get("content-type", "image/jpeg"),
        headers={"Cache-Control": "private, max-age=600"},
    )
