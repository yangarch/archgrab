from __future__ import annotations

import shutil
import subprocess
from functools import lru_cache

from fastapi import APIRouter

from app.extractors import gallerydl_engine

router = APIRouter(tags=["health"])


@lru_cache
def _engine_versions() -> dict[str, str | None]:
    import yt_dlp

    versions: dict[str, str | None] = {"yt_dlp": yt_dlp.version.__version__}
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
async def engines() -> dict[str, str | None]:
    """추출 엔진 버전 — 인스타 추출이 깨졌을 때 가장 먼저 보는 화면."""
    return _engine_versions()
