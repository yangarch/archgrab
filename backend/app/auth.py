"""단일 사용자 비밀번호 로그인 + 서명 세션 쿠키."""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque

from fastapi import Depends, Request, Response
from itsdangerous import BadSignature, SignatureExpired

from app.config import Settings, get_settings
from app.core.errors import ErrorCode, ArchGrabError
from app.core.security import get_serializer, verify_password

SESSION_COOKIE = "ag_session"
_SALT = "session"

_attempts: dict[str, deque[float]] = defaultdict(deque)


def _client_ip(request: Request) -> str:
    # 터널/리버스 프록시 뒤에 두는 구성이라 XFF 를 우선 본다.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _check_rate_limit(request: Request, settings: Settings) -> None:
    now = time.monotonic()
    bucket = _attempts[_client_ip(request)]
    while bucket and now - bucket[0] > settings.login_window:
        bucket.popleft()
    if len(bucket) >= settings.login_max_attempts:
        raise ArchGrabError(
            ErrorCode.RATE_LIMITED, "로그인 시도가 너무 많습니다. 1분 후 다시 시도해주세요."
        )


def _record_failure(request: Request) -> None:
    _attempts[_client_ip(request)].append(time.monotonic())


def issue_session(response: Response, settings: Settings) -> None:
    token = get_serializer(_SALT).dumps({"sub": "owner"})
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_max_age,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def clear_session(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


async def login(request: Request, response: Response, password: str) -> None:
    settings = get_settings()
    if not settings.password_hash:
        raise ArchGrabError(
            ErrorCode.INTERNAL,
            "비밀번호가 설정되지 않았습니다. `make hashpw` 결과를 .env 에 넣어주세요.",
        )
    _check_rate_limit(request, settings)
    if not verify_password(password, settings.password_hash):
        _record_failure(request)
        await asyncio.sleep(0.4)          # 무차별 대입 속도를 늦춘다
        raise ArchGrabError(ErrorCode.LOGIN_REQUIRED, "비밀번호가 올바르지 않습니다.")
    issue_session(response, settings)


def is_authenticated(request: Request) -> bool:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return False
    try:
        get_serializer(_SALT).loads(token, max_age=get_settings().session_max_age)
    except (BadSignature, SignatureExpired, RuntimeError):
        return False
    return True


async def require_auth(request: Request) -> None:
    """모든 /api 라우터(로그인·헬스 제외)에 걸리는 의존성."""
    if not is_authenticated(request):
        raise ArchGrabError(ErrorCode.LOGIN_REQUIRED, "로그인이 필요합니다.")


AuthRequired = Depends(require_auth)
