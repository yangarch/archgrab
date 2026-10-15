"""스레드 — 엔진이 하나다.

인스타와 달리 폴백이 없다. gallery-dl 과 yt-dlp 둘 다 스레드 추출기가 없어서
(확인함) `threads-web` 이 유일한 경로다. 그래서 인스타처럼 엔진 순서를 고르는
분기가 없고, 대신 실패 원인을 그대로 올려보낸다.

내려받기는 다른 플랫폼과 같은 한 경로(`fetch_pairs`)로 모은다 — 진행률·파일명을
우리가 통제하고 재인코딩이 끼어들 여지가 없다. 스레드의 포맷은 전부
progressive mp4 와 단일 이미지라 mux 가 필요한 경우가 없다.
"""

from __future__ import annotations

from pathlib import Path

from app.config import get_settings
from app.core import secrets_store
from app.core.cache import media_cache
from app.core.errors import ArchGrabError, ErrorCode
from app.core.models import FormatOption, MediaInfo, MediaItem
from app.core.url import Kind, ParsedUrl
from app.extractors import threads_web
from app.extractors.base import ProgressCallback, Selection, noop_progress
from app.extractors.common import (
    fetch_pairs,
    media_filename,
    reject_unsupported_kinds,
)

NAME = "threads"
REFERER = "https://www.threads.com/"

# 파싱은 되지만 처리기가 없는 종류. 선언은 플랫폼마다, 거절은 common 한 곳에서.
UNSUPPORTED_KINDS = {
    Kind.PROFILE: "프로필 주소는 아직 지원하지 않습니다. 개별 게시글 주소를 넣어주세요.",
}
PROFILE_UNSUPPORTED = UNSUPPORTED_KINDS[Kind.PROFILE]


def _pick_format(item: MediaItem, wanted_id: str | None) -> FormatOption | None:
    """고른 포맷, 없으면 첫 번째.

    프론트가 화면에 보여주는 것도 formats[0] 이다 — 둘이 같은 값을 쓰면
    "보이는 것"과 "받는 것"이 어긋날 수 없다.
    """
    if wanted_id:
        for candidate in item.formats:
            if candidate.id == wanted_id:
                return candidate
    return item.formats[0] if item.formats else None


class ThreadsExtractor:
    name = NAME

    def probe(self, parsed: ParsedUrl) -> MediaInfo:
        reject_unsupported_kinds(parsed, UNSUPPORTED_KINDS)
        with secrets_store.cookie_file(NAME) as cookies:
            return threads_web.probe(parsed, cookies)

    def download(
        self,
        parsed: ParsedUrl,
        selection: Selection,
        dest: Path,
        progress: ProgressCallback = noop_progress,
    ) -> list[Path]:
        reject_unsupported_kinds(parsed, UNSUPPORTED_KINDS)
        with secrets_store.cookie_file(NAME) as cookies:
            max_age = get_settings().resolve_cache_seconds

            # 방금 해석한 결과를 재사용한다. 담긴 CDN 주소는 서명·만료가 붙어
            # 있으므로 받다가 실패하면 캐시를 버리고 신선한 주소로 한 번 더 한다.
            for attempt in (0, 1):
                media = None if attempt else self._cached(parsed, cookies, max_age)
                if media is None:
                    media = threads_web.probe(parsed, cookies)
                    media_cache.put(parsed.cache_key, media)

                pairs = self._pairs_for(parsed, media, selection)
                if not pairs:
                    raise ArchGrabError(ErrorCode.ENGINE_FAILED, "내려받을 포맷을 찾지 못했습니다.")

                try:
                    return fetch_pairs(pairs, dest, cookies, progress, referer=REFERER)
                except ArchGrabError:
                    if attempt:
                        raise
                    media_cache.invalidate(parsed.cache_key)

            raise ArchGrabError(ErrorCode.ENGINE_FAILED)

    @staticmethod
    def _cached(parsed: ParsedUrl, cookies: Path | None, max_age: float) -> MediaInfo | None:
        cached = media_cache.get(parsed.cache_key, max_age)
        if cached is None:
            return None
        if cached.used_cookies != (cookies is not None):
            return None
        if cached.engine != threads_web.NAME:
            return None
        return cached

    @staticmethod
    def _pairs_for(
        parsed: ParsedUrl, media: MediaInfo, selection: Selection
    ) -> list[tuple[str, str]]:
        wanted = [item for item in media.items if selection.wants(item.id)] or media.items
        # 작업에 담긴 개수가 아니라 게시글의 항목 수로 번호를 붙인다. 9장 중 한
        # 장만 받아도 번호가 있어야 여러 번 받았을 때 파일명이 겹치지 않는다.
        multiple = len(media.items) > 1

        pairs: list[tuple[str, str]] = []
        for item in wanted:
            chosen = _pick_format(item, selection.format_for(item.id))
            if chosen is None or not chosen.url:
                continue
            pairs.append((
                media_filename("threads", parsed, media, item, chosen, numbered=multiple),
                chosen.url,
            ))
        return pairs


extractor = ThreadsExtractor()
