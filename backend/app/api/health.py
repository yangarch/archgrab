from __future__ import annotations

import shutil
import subprocess
from functools import lru_cache

from fastapi import APIRouter

from app.extractors import gallerydl_engine

router = APIRouter(tags=["health"])


@lru_cache
def _impersonate_targets() -> int:
    """yt-dlp 가 쓸 수 있는 브라우저 TLS 위장 타겟 수.

    0 이면 curl_cffi 가 없다는 뜻이고, 그러면 인스타의 비로그인 GraphQL 경로가
    조용히 비활성된다 — 공개 게시글까지 "로그인 필요"처럼 실패하므로 진단에 노출한다.
    """
    try:
        from yt_dlp import YoutubeDL

        with YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
            return len(ydl._get_available_impersonate_targets())
    except Exception:
        return 0


@lru_cache
def _engine_versions() -> dict[str, object]:
    import yt_dlp

    targets = _impersonate_targets()
    versions: dict[str, object] = {
        "yt_dlp": yt_dlp.version.__version__,
        "impersonate_targets": targets,
        # 쿠키 없이 공개 인스타 콘텐츠를 받을 수 있는 상태인가
        "anonymous_instagram": targets > 0,
    }
    versions["ffmpeg"] = _probe(["ffmpeg", "-version"])
    versions["gallery_dl"] = gallerydl_engine.version()
    return versions


def _probe(cmd: list[str]) -> str | None:
    if not shutil.which(cmd[0]):
        return None
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=10)  # noqa: S603
    except (OSError, subprocess.SubprocessError):
        return None
    first = (out.stdout or out.stderr).splitlines()
    return first[0].strip() if first else None


@router.get("/health")
async def health() -> dict[str, object]:
    """컨테이너 헬스체크용. 인증 없이 열려 있으므로 최소 정보만 담는다."""
    return {"status": "ok"}


@router.get("/engines")
async def engines() -> dict[str, object]:
    """추출 엔진 상태 — 인스타 추출이 깨졌을 때 가장 먼저 보는 화면."""
    return _engine_versions()
