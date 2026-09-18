"""URL 해석 — 메타데이터만 가져온다. 실제 바이트는 작업 단계에서 받는다."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.auth import AuthRequired
from app.config import get_settings
from app.core.cache import media_cache
from app.core.models import MediaInfo
from app.core.url import parse_url
from app.extractors import registry
from app.media.storage import make_thumb_token

router = APIRouter(tags=["resolve"], dependencies=[AuthRequired])


class ResolveRequest(BaseModel):
    url: str = Field(min_length=4, max_length=2048)


class ResolveResponse(BaseModel):
    info: MediaInfo
    cached: bool = False


def _proxy_thumbnails(info: MediaInfo) -> MediaInfo:
    """CDN 이 핫링크를 막아도 미리보기가 보이도록 우리 쪽으로 중계한다."""
    clone = info.model_copy(deep=True)
    for item in clone.items:
        if item.thumbnail and item.thumbnail.startswith(("http://", "https://")):
            item.thumbnail = f"/api/thumb/{make_thumb_token(item.thumbnail)}"
    return clone


@router.post("/resolve", response_model=ResolveResponse)
async def resolve(payload: ResolveRequest) -> ResolveResponse:
    parsed = parse_url(payload.url)

    cached = media_cache.get(parsed.cache_key, get_settings().resolve_cache_seconds)
    if cached is not None:
        return ResolveResponse(info=_proxy_thumbnails(cached), cached=True)

    extractor = registry.get_extractor(parsed.platform)
    # 엔진 호출은 블로킹이라 스레드로 넘긴다
    info = await asyncio.to_thread(extractor.probe, parsed)
    # 다운로드 경로가 같은 캐시를 읽어 재추출을 건너뛴다
    media_cache.put(parsed.cache_key, info)
    return ResolveResponse(info=_proxy_thumbnails(info), cached=False)
