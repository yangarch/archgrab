"""X (트위터) — gallery-dl 하나로 사진·동영상을 모두 처리한다.

인스타와 달리 단순하다. 실측으로 확인한 것:

- gallery-dl 이 **익명으로 동작한다**. 인스타는 어떤 옵션을 줘도 로그인
  페이지로 리다이렉트돼서 `instagram_web` 엔진을 직접 만들어야 했지만, X 는
  그냥 된다.
- 사진 트윗도 익명으로 받는다 (`type=photo`, 1477x1108 확인).
- yt-dlp 는 사진 트윗에서 "No video could be found" 로 실패한다 — 인스타와
  같은 한계다. 그래서 동영상 폴백으로만 둔다.
- 메타데이터에 `type`(photo/video/animated_gif)과 `num`/`count` 가 있어
  종류 구분과 캐러셀 정규화가 그대로 된다.

쿠키는 필수가 아니다. 비공개 계정이나 민감 콘텐츠에만 필요하다.
"""

from __future__ import annotations

from pathlib import Path

from app.config import get_settings
from app.core import secrets_store
from app.core.cache import media_cache
from app.core.errors import ArchGrabError, ErrorCode
from app.core.models import FormatOption, MediaInfo, MediaItem
from app.core.url import ParsedUrl
from app.extractors import gallerydl_engine, ytdlp_engine
from app.extractors.base import ProgressCallback, Selection, noop_progress
from app.extractors.common import fetch_pairs, first_text, media_filename, parse_timestamp
from app.extractors.gallerydl_engine import GalleryEntry

NAME = "x"
PREFIX = "x"
REFERER = "https://x.com/"
GALLERY_DL = "gallery-dl"
YT_DLP = "yt-dlp"
ORIGINAL_FORMAT_ID = "original"

# gallery-dl 의 type → 우리 MediaType.
# animated_gif 는 X 가 mp4 로 서빙하므로 동영상으로 다룬다.
_TYPE_MAP = {"photo": "image", "video": "video", "animated_gif": "video"}


def engine_order() -> tuple[str, ...]:
    """gallery-dl 이 사진·동영상을 다 처리하므로 주력이고, yt-dlp 는 동영상 폴백."""
    return (GALLERY_DL, YT_DLP)


class XExtractor:
    name = NAME

    def probe(self, parsed: ParsedUrl) -> MediaInfo:
        with secrets_store.cookie_file(NAME) as cookies:
            failures: list[ArchGrabError] = []
            for engine in engine_order():
                try:
                    if engine == GALLERY_DL:
                        entries, post = gallerydl_engine.dump(parsed.url, cookies)
                        info = to_media_info(parsed, entries, post,
                                             used_cookies=cookies is not None)
                        media_cache.put(parsed.cache_key, info)
                        return info
                    raw = ytdlp_engine.extract(parsed.url, cookies)
                    return ytdlp_engine.to_media_info(
                        parsed, raw, used_cookies=cookies is not None
                    )
                except ArchGrabError as exc:
                    failures.append(exc)
            raise failures[0]

    def download(
        self,
        parsed: ParsedUrl,
        selection: Selection,
        dest: Path,
        progress: ProgressCallback = noop_progress,
    ) -> list[Path]:
        with secrets_store.cookie_file(NAME) as cookies:
            max_age = get_settings().resolve_cache_seconds

            # 방금 해석한 결과를 재사용한다. 서명 URL 이 만료됐을 수 있으니
            # 실패하면 캐시를 버리고 한 번 다시 추출한다 (인스타와 같은 규칙).
            for attempt in (0, 1):
                media = None if attempt else self._cached(parsed, cookies, max_age)
                if media is None:
                    entries, post = gallerydl_engine.dump(parsed.url, cookies)
                    media = to_media_info(parsed, entries, post,
                                          used_cookies=cookies is not None)
                    media_cache.put(parsed.cache_key, media)

                pairs = self._pairs(parsed, media, selection)
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
        if cached is None or cached.engine != GALLERY_DL:
            return None
        if cached.used_cookies != (cookies is not None):
            return None
        return cached

    @staticmethod
    def _pairs(
        parsed: ParsedUrl, media: MediaInfo, selection: Selection
    ) -> list[tuple[str, str]]:
        wanted = [item for item in media.items if selection.wants(item.id)] or media.items
        numbered = len(media.items) > 1

        pairs: list[tuple[str, str]] = []
        for item in wanted:
            chosen = next(
                (f for f in item.formats if f.id == selection.format_for(item.id)),
                item.formats[0] if item.formats else None,
            )
            if chosen is None or not chosen.url:
                continue
            pairs.append((
                media_filename(PREFIX, parsed, media, item, chosen, numbered=numbered),
                chosen.url,
            ))
        return pairs


def _media_type(entry: GalleryEntry) -> str:
    declared = str(entry.meta.get("type") or "").lower()
    # gallery-dl 이 type 을 직접 준다. 없을 때만 확장자로 추측한다.
    return _TYPE_MAP.get(declared) or entry.media_type


def to_media_info(
    parsed: ParsedUrl,
    entries: list[GalleryEntry],
    post: dict,
    *,
    used_cookies: bool,
) -> MediaInfo:
    items: list[MediaItem] = []
    for index, entry in enumerate(entries):
        kind = _media_type(entry)
        width = entry.dimension("width")
        height = entry.dimension("height")
        items.append(
            MediaItem(
                id=str(index),
                index=index,
                type=kind,  # type: ignore[arg-type]
                thumbnail=entry.url if kind == "image" else None,
                duration=entry.meta.get("duration"),
                width=width,
                height=height,
                formats=[
                    FormatOption(
                        id=ORIGINAL_FORMAT_ID,
                        ext=entry.extension,
                        width=width,
                        height=height,
                        note="원본",
                        url=entry.url,
                        protocol="https",
                    )
                ],
            )
        )

    meta = post or (entries[0].meta if entries else {})
    author = meta.get("author") or meta.get("user") or {}
    username = author.get("name") if isinstance(author, dict) else None
    username = username or parsed.username
    text = first_text(meta, "content", "description")

    return MediaInfo(
        platform=parsed.platform,
        kind=parsed.kind,
        source_url=parsed.url,
        key=parsed.key,
        title=text,
        uploader=username,
        uploader_url=f"https://x.com/{username}" if username else None,
        description=text,
        taken_at=parse_timestamp(meta.get("date")),
        items=items,
        engine=GALLERY_DL,
        used_cookies=used_cookies,
    )


extractor = XExtractor()
