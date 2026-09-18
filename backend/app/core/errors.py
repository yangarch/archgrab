"""사용자에게 그대로 보여줄 수 있는 오류 분류."""

from __future__ import annotations

import re
from enum import StrEnum


class ErrorCode(StrEnum):
    UNSUPPORTED = "UNSUPPORTED"
    LOGIN_REQUIRED = "LOGIN_REQUIRED"
    PRIVATE = "PRIVATE"
    NOT_FOUND = "NOT_FOUND"
    RATE_LIMITED = "RATE_LIMITED"
    GEO_BLOCKED = "GEO_BLOCKED"
    ENGINE_FAILED = "ENGINE_FAILED"
    TIMEOUT = "TIMEOUT"
    INTERNAL = "INTERNAL"


MESSAGES: dict[ErrorCode, str] = {
    ErrorCode.UNSUPPORTED: "지원하지 않는 주소입니다. 인스타그램·X·유튜브 링크를 넣어주세요.",
    ErrorCode.LOGIN_REQUIRED: "로그인이 필요한 콘텐츠입니다. 설정에서 쿠키를 등록해주세요.",
    ErrorCode.PRIVATE: "비공개 계정이거나 접근 권한이 없는 콘텐츠입니다.",
    ErrorCode.NOT_FOUND: "삭제되었거나 존재하지 않는 콘텐츠입니다.",
    ErrorCode.RATE_LIMITED: "플랫폼이 요청을 일시 차단했습니다. 잠시 후 다시 시도해주세요.",
    ErrorCode.GEO_BLOCKED: "지역 제한이 걸린 콘텐츠입니다.",
    ErrorCode.ENGINE_FAILED: "추출에 실패했습니다. 엔진 업데이트(make update-engines) 후 다시 시도해보세요.",
    ErrorCode.TIMEOUT: "시간이 초과되었습니다. 다시 시도해주세요.",
    ErrorCode.INTERNAL: "내부 오류가 발생했습니다.",
}

HTTP_STATUS: dict[ErrorCode, int] = {
    ErrorCode.UNSUPPORTED: 400,
    ErrorCode.LOGIN_REQUIRED: 401,
    ErrorCode.PRIVATE: 403,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.RATE_LIMITED: 429,
    ErrorCode.GEO_BLOCKED: 451,
    ErrorCode.ENGINE_FAILED: 502,
    ErrorCode.TIMEOUT: 504,
    ErrorCode.INTERNAL: 500,
}


class ArchGrabError(Exception):
    """API 응답과 작업 실패 기록에 함께 쓰는 예외."""

    def __init__(
        self,
        code: ErrorCode,
        message: str | None = None,
        *,
        detail: str | None = None,
    ) -> None:
        self.code = code
        self.message = message or MESSAGES[code]
        self.detail = detail
        super().__init__(self.message)

    @property
    def http_status(self) -> int:
        return HTTP_STATUS[self.code]

    def to_payload(self) -> dict[str, str | None]:
        return {"code": self.code.value, "message": self.message, "detail": self.detail}


# yt-dlp / gallery-dl 이 내놓는 문장을 원인 코드로 접는다.
# 엔진 문구는 버전마다 바뀌므로 넓게 잡고, 못 알아본 건 ENGINE_FAILED 로 남긴다.
_PATTERNS: tuple[tuple[re.Pattern[str], ErrorCode], ...] = (
    (re.compile(
        r"login required|requires? (a )?login|sign ?in to confirm|authentication"
        # 인스타는 비로그인 요청을 로그인 페이지로 돌려보내는 식으로도 막는다
        r"|login page|redirect(ed)? to .*log ?in|log ?in to (continue|view)",
        re.I,
     ), ErrorCode.LOGIN_REQUIRED),
    (re.compile(r"\b(401|403)\b|forbidden|not authorized|unauthorized", re.I),
     ErrorCode.LOGIN_REQUIRED),
    (re.compile(r"private|only available to|not available to you", re.I), ErrorCode.PRIVATE),
    (re.compile(r"\b404\b|not found|unavailable|been removed|deleted|no longer exists", re.I),
     ErrorCode.NOT_FOUND),
    (re.compile(r"\b429\b|rate.?limit|too many requests|try again later|temporarily blocked", re.I),
     ErrorCode.RATE_LIMITED),
    (re.compile(r"geo.?(restrict|block)|not available in your country", re.I), ErrorCode.GEO_BLOCKED),
    (re.compile(r"timed? ?out|timeout", re.I), ErrorCode.TIMEOUT),
)


def classify_engine_error(text: str) -> ErrorCode:
    for pattern, code in _PATTERNS:
        if pattern.search(text):
            return code
    return ErrorCode.ENGINE_FAILED


def from_engine_error(text: str) -> ArchGrabError:
    """엔진 원문을 detail 로 보존하면서 사용자용 메시지를 붙인다."""
    return ArchGrabError(classify_engine_error(text), detail=text.strip()[:600] or None)
