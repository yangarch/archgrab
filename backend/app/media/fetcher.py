"""CDN 원본을 그대로 스트리밍해 파일로 떨어뜨린다.

gallery-dl 이 알려준 서명 URL 을 우리가 직접 받는다. 진행률·파일명·저장 위치를
우리가 통제할 수 있고, 무엇보다 재인코딩이 끼어들 여지가 없다.
"""

from __future__ import annotations

from collections.abc import Callable
from http.cookiejar import LoadError, MozillaCookieJar
from pathlib import Path

import httpx

from app.config import get_settings
from app.core.errors import ErrorCode, ArchGrabError, from_engine_error

CHUNK = 256 * 1024

# CDN 이 브라우저 요청처럼 보이는 편을 선호한다.
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
}

# (받은 바이트, 전체 바이트 or None)
ByteProgress = Callable[[int, int | None], None]


def _load_jar(cookies: Path | None) -> MozillaCookieJar | None:
    if cookies is None:
        return None
    jar = MozillaCookieJar(str(cookies))
    try:
        jar.load(ignore_discard=True, ignore_expires=True)
    except (OSError, LoadError):
        return None
    return jar


def fetch_to_file(
    url: str,
    dest: Path,
    *,
    referer: str | None = None,
    cookies: Path | None = None,
    progress: ByteProgress | None = None,
) -> int:
    """받은 바이트 수를 반환. 중간에 죽어도 .part 만 남고 dest 는 생기지 않는다."""
    settings = get_settings()
    headers = dict(DEFAULT_HEADERS)
    if referer:
        headers["Referer"] = referer

    part = dest.with_name(dest.name + ".part")
    written = 0

    try:
        with httpx.Client(
            follow_redirects=True,
            timeout=httpx.Timeout(30.0, read=120.0),
            headers=headers,
            cookies=_load_jar(cookies),
            proxy=settings.proxy,
        ) as client, client.stream("GET", url) as response:
            if response.status_code >= 400:
                raise from_engine_error(f"HTTP {response.status_code} — {url.split('?')[0]}")
            total = int(response.headers.get("content-length") or 0) or None
            with part.open("wb") as handle:
                for chunk in response.iter_bytes(CHUNK):
                    handle.write(chunk)
                    written += len(chunk)
                    if progress:
                        progress(written, total)
    except httpx.TimeoutException as exc:
        part.unlink(missing_ok=True)
        raise ArchGrabError(ErrorCode.TIMEOUT, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        part.unlink(missing_ok=True)
        raise ArchGrabError(ErrorCode.ENGINE_FAILED, detail=str(exc)) from exc
    except ArchGrabError:
        part.unlink(missing_ok=True)
        raise

    if written == 0:
        part.unlink(missing_ok=True)
        raise ArchGrabError(ErrorCode.ENGINE_FAILED, detail="빈 응답")

    part.replace(dest)
    return written
