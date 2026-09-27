"""공유 링크를 실제 게시글 주소로 바꾼다.

인스타 앱의 공유 버튼은 `instagram.com/share/...` 를, X 는 `t.co/...` 를 준다.
파서(`core/url.py`)는 네트워크를 타지 않는 계층이라 `needs_redirect` 로 표시만
하고, 실제 추적은 여기서 한다.

추적하지 않으면 공유 코드를 숏코드로 착각해 엉뚱한 media_id 가 만들어지고,
GraphQL 이 빈 응답을 주는 바람에 **공개 게시글인데도 "비공개·삭제·제한"** 이라는
틀린 안내가 나간다. 모바일 공유 버튼이 주는 형태라 실사용에서 가장 먼저 부딪친다.

리다이렉트가 없고 JS 로 그리는 껍데기만 오는 경우도 있어, 본문의 canonical /
og:url 도 함께 본다.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from app.config import get_settings
from app.core.errors import ArchGrabError, ErrorCode
from app.core.url import ParsedUrl, parse_url

# (최종 URL, 본문) 을 돌려주는 함수
Fetcher = Callable[[str], tuple[str, str]]

_CANONICAL = re.compile(
    r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)["\']', re.I
)
_OG_URL = re.compile(
    r'<meta[^>]+property=["\']og:url["\'][^>]+content=["\']([^"\']+)["\']', re.I
)
_LOGIN_PATHS = ("/accounts/login", "/login")

MAX_BODY = 512 * 1024


def _default_fetch(url: str) -> tuple[str, str]:
    """한 번 따라가서 (최종 URL, 본문) 을 돌려준다.

    curl_cffi 를 먼저 쓴다. 다만 이건 안전한 기본값일 뿐이고, 리다이렉트 추적
    자체는 위장 없이도 된다 — 실측으로 확인했다(httpx 로도 인스타
    /p/{code} 리다이렉트가 로그인으로 밀리지 않고 정상 추적됨). 위장이 반드시
    필요한 건 GraphQL 경로쪽이다(`instagram_web` 참고). /share/ 가 그쪽과 같은
    게이팅을 받는지는 확인하지 못했으므로, 더 강한 쪽을 기본으로 둔다.
    """
    settings = get_settings()
    try:
        from curl_cffi import requests as curl_requests

        with curl_requests.Session(
            impersonate="chrome", timeout=settings.engine_timeout, proxy=settings.proxy
        ) as session:
            response = session.get(url, allow_redirects=True)
            return str(response.url), (response.text or "")[:MAX_BODY]
    except ImportError:
        pass

    import httpx

    with httpx.Client(
        follow_redirects=True, timeout=30.0, proxy=settings.proxy
    ) as client:
        response = client.get(url)
        return str(response.url), response.text[:MAX_BODY]


def _from_body(body: str) -> str | None:
    for pattern in (_CANONICAL, _OG_URL):
        match = pattern.search(body)
        if match:
            return match.group(1)
    return None


def follow(parsed: ParsedUrl, fetch: Fetcher | None = None) -> ParsedUrl:
    """공유 링크면 실제 주소로 바꿔 돌려준다. 아니면 그대로 반환한다."""
    if not parsed.needs_redirect:
        return parsed

    fetch = fetch or _default_fetch
    try:
        final_url, body = fetch(parsed.url)
    except ArchGrabError:
        raise
    except Exception as exc:
        raise ArchGrabError(
            ErrorCode.ENGINE_FAILED,
            "공유 링크의 실제 주소를 확인하지 못했습니다. 게시글 링크를 직접 넣어주세요.",
            detail=str(exc),
        ) from exc

    if any(path in final_url for path in _LOGIN_PATHS):
        raise ArchGrabError(
            ErrorCode.LOGIN_REQUIRED,
            "공유 링크가 로그인 페이지로 이동했습니다. 쿠키를 등록하거나 "
            "게시글 링크를 직접 넣어주세요.",
        )

    candidates = [final_url]
    from_body = _from_body(body)
    if from_body:
        candidates.append(from_body)

    for candidate in candidates:
        try:
            resolved = parse_url(candidate)
        except ArchGrabError:
            continue
        # 여전히 공유 링크면 추적이 안 된 것 — 엔진에 넘기면 엉뚱한 id 가 만들어진다
        if resolved.needs_redirect:
            continue
        return resolved

    raise ArchGrabError(
        ErrorCode.UNSUPPORTED,
        "공유 링크에서 게시글을 찾지 못했습니다. 앱에서 '링크 복사' 대신 "
        "게시글 주소를 직접 넣어주세요.",
    )
