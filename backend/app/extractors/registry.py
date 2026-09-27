"""플랫폼 → 추출기 매핑. 새 플랫폼은 여기 한 줄만 추가한다."""

from __future__ import annotations

from app.core.errors import ErrorCode, ArchGrabError
from app.core.url import Platform
from app.extractors import instagram, x, youtube
from app.extractors.base import Extractor

_EXTRACTORS: dict[Platform, Extractor] = {
    Platform.INSTAGRAM: instagram.extractor,
    Platform.X: x.extractor,
    Platform.YOUTUBE: youtube.extractor,
}

# 사용자에게 보이는 문구다 — 내부 마일스톤 번호는 쓰지 않는다.
_PENDING: dict[Platform, str] = {}


def get_extractor(platform: Platform) -> Extractor:
    extractor = _EXTRACTORS.get(platform)
    if extractor is None:
        raise ArchGrabError(ErrorCode.UNSUPPORTED, _PENDING.get(platform, "지원하지 않습니다."))
    return extractor


def supported_platforms() -> list[str]:
    return [p.value for p in _EXTRACTORS]
