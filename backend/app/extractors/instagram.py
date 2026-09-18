"""인스타그램 — gallery-dl 주력, yt-dlp 폴백.

gallery-dl 이 게시글·릴스·캐러셀·스토리를 통틀어 가장 안정적이고, 이미지와 동영상을
한 번에 내놓는다. 실패하면 yt-dlp 로 한 번 더 시도한다. 둘 다 실패하면 **첫 엔진의
원인 코드**를 올린다 — 폴백의 일반적인 실패 메시지보다 그쪽이 훨씬 구체적이다.

내려받기는 gallery-dl 이 알려준 CDN 주소를 우리가 직접 스트리밍한다. 서명 URL 은
시간이 지나면 만료되므로 작업 시작 시점에 다시 추출해 신선한 주소를 쓴다.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from app.core import secrets_store
from app.core.errors import ErrorCode, ArchGrabError
from app.core.models import FormatOption, MediaInfo, MediaItem
from app.core.url import Kind, ParsedUrl
from app.extractors import gallerydl_engine, ytdlp_engine
from app.extractors.base import ProgressCallback, ProgressEvent, Selection, noop_progress
from app.extractors.gallerydl_engine import GalleryEntry
from app.media import fetcher
from app.media.storage import safe_name

NAME = "instagram"
REFERER = "https://www.instagram.com/"

# 쿠키가 없으면 애초에 안 되는 종류 — 엔진을 때리기 전에 걸러낸다.
COOKIE_REQUIRED_KINDS = frozenset({Kind.STORY, Kind.HIGHLIGHT})

ORIGINAL_FORMAT_ID = "original"


class InstagramExtractor:
    name = NAME

    # ---- 해석 ------------------------------------------------------------
    def probe(self, parsed: ParsedUrl) -> MediaInfo:
        with secrets_store.cookie_file(NAME) as cookies:
            self._require_cookies(parsed, cookies)
            try:
                entries, post = gallerydl_engine.dump(parsed.url, cookies)
                return _to_media_info(parsed, entries, post, used_cookies=cookies is not None)
            except ArchGrabError as primary:
                try:
                    info = ytdlp_engine.extract(parsed.url, cookies)
                except ArchGrabError:
                    raise primary from None
                return ytdlp_engine.to_media_info(
                    parsed, info, used_cookies=cookies is not None
                )

    # ---- 내려받기 --------------------------------------------------------
    def download(
        self,
        parsed: ParsedUrl,
        selection: Selection,
        dest: Path,
        progress: ProgressCallback = noop_progress,
    ) -> list[Path]:
        with secrets_store.cookie_file(NAME) as cookies:
            self._require_cookies(parsed, cookies)
            try:
                entries, post = gallerydl_engine.dump(parsed.url, cookies)
            except ArchGrabError as primary:
                try:
                    return ytdlp_engine.download(
                        parsed.url, dest, selection=selection, cookies=cookies, progress=progress
                    )
                except ArchGrabError:
                    raise primary from None

            chosen = [
                (index, entry)
                for index, entry in enumerate(entries)
                if selection.wants(str(index))
            ]
            if not chosen:
                chosen = list(enumerate(entries))

            return self._fetch_all(parsed, chosen, post, dest, cookies, progress)

    def _fetch_all(
        self,
        parsed: ParsedUrl,
        chosen: list[tuple[int, GalleryEntry]],
        post: dict,
        dest: Path,
        cookies: Path | None,
        progress: ProgressCallback,
    ) -> list[Path]:
        event = ProgressEvent(count=len(chosen))
        paths: list[Path] = []
        multiple = len(chosen) > 1

        for position, (index, entry) in enumerate(chosen, start=1):
            name = _filename(parsed, entry, post, index=index, numbered=multiple)
            target = dest / name
            event.index = position
            event.current = name

            def on_bytes(done: int, total: int | None, _event: ProgressEvent = event) -> None:
                _event.done_bytes = done
                _event.total_bytes = total
                progress(_event)

            fetcher.fetch_to_file(
                entry.url, target, referer=REFERER, cookies=cookies, progress=on_bytes
            )
            paths.append(target)

        return paths

    @staticmethod
    def _require_cookies(parsed: ParsedUrl, cookies: Path | None) -> None:
        if cookies is None and parsed.kind in COOKIE_REQUIRED_KINDS:
            raise ArchGrabError(
                ErrorCode.LOGIN_REQUIRED,
                "스토리는 로그인이 필요합니다. 설정에서 인스타그램 쿠키를 등록해주세요.",
            )


# ---- 정규화 --------------------------------------------------------------

def _first(meta: dict, *keys: str) -> str | None:
    for key in keys:
        value = meta.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _taken_at(meta: dict) -> datetime | None:
    raw = meta.get("date")
    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    if isinstance(raw, int | float) and raw > 0:
        try:
            return datetime.fromtimestamp(raw)
        except (OSError, OverflowError, ValueError):
            return None
    return None


def _to_media_info(
    parsed: ParsedUrl,
    entries: list[GalleryEntry],
    post: dict,
    *,
    used_cookies: bool,
) -> MediaInfo:
    items: list[MediaItem] = []

    for index, entry in enumerate(entries):
        width = entry.dimension("width")
        height = entry.dimension("height")
        items.append(
            MediaItem(
                id=str(index),
                index=index,
                type=entry.media_type,  # type: ignore[arg-type]
                title=_first(entry.meta, "description", "title"),
                # 동영상은 포스터 이미지를, 이미지는 자기 자신을 썸네일로 쓴다
                thumbnail=_first(entry.meta, "display_url", "thumbnail")
                or (entry.url if entry.media_type == "image" else None),
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
                    )
                ],
            )
        )

    meta = post or (entries[0].meta if entries else {})
    username = _first(meta, "username", "owner_username", "user") or parsed.username

    return MediaInfo(
        platform=parsed.platform,
        kind=parsed.kind,
        source_url=parsed.url,
        key=parsed.key,
        title=_first(meta, "description", "title"),
        uploader=username,
        uploader_url=f"https://www.instagram.com/{username}/" if username else None,
        description=_first(meta, "description"),
        taken_at=_taken_at(meta),
        items=items,
        engine="gallery-dl",
        used_cookies=used_cookies,
    )


def _filename(
    parsed: ParsedUrl, entry: GalleryEntry, post: dict, *, index: int, numbered: bool
) -> str:
    meta = post or entry.meta
    username = _first(meta, "username", "owner_username") or parsed.username or "unknown"
    key = parsed.key or _first(entry.meta, "post_shortcode", "shortcode") or "item"
    suffix = f"_{index + 1}" if numbered else ""
    return safe_name(f"instagram_{username}_{key}{suffix}.{entry.extension}")


extractor = InstagramExtractor()
