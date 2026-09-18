"""인스타그램 — 쿠키 유무에 따라 엔진을 바꾼다.

**쿠키 없음 → yt-dlp 만.** yt-dlp 는 TLS 지문 위장(curl_cffi)으로 인스타의
비로그인 GraphQL 경로(`PolarisLoggedOutDesktopWWWPostRootContentQuery`,
응답 필드 `if_not_gated_logged_out`)를 쓸 수 있어 공개 게시글·릴스·캐러셀을
쿠키 없이 받는다. 실제 게시글로 확인했다.

**쿠키 있음 → gallery-dl 우선, yt-dlp 폴백.** gallery-dl 은 이미지·캐러셀
메타데이터가 더 정확하고 원본 URL 을 직접 준다. 단 익명 접근은 불가능하다 —
`browser=firefox`·`browser=chrome`·`api=graphql` 모두 로그인 페이지로
리다이렉트된다(확인함). 그래서 쿠키가 없을 때는 아예 호출하지 않는다.
호출하면 시간만 쓰고 "로그인 필요"라는 오해를 부르는 에러를 낸다.

내려받기는 두 엔진 모두 **원본 CDN 주소를 우리가 직접 스트리밍**하는 한 경로로
모은다. 진행률·파일명을 우리가 통제하고 재인코딩이 끼어들 여지가 없다. 직접 받을
수 없는 포맷(DASH·HLS)만 yt-dlp 의 다운로더에 맡긴다.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from app.config import get_settings
from app.core import secrets_store
from app.core.cache import media_cache
from app.core.errors import ArchGrabError, ErrorCode
from app.core.models import FormatOption, MediaInfo, MediaItem
from app.core.url import Kind, ParsedUrl
from app.extractors import gallerydl_engine, instagram_web, ytdlp_engine
from app.extractors.base import ProgressCallback, ProgressEvent, Selection, noop_progress
from app.extractors.gallerydl_engine import GalleryEntry
from app.media import fetcher
from app.media.storage import safe_name

NAME = "instagram"
REFERER = "https://www.instagram.com/"
ORIGINAL_FORMAT_ID = "original"

# 쿠키가 없으면 애초에 안 되는 종류 — 엔진을 때리기 전에 걸러낸다.
# 스토리는 설계상 로그인한 사용자에게만 보이므로 익명 경로가 존재하지 않는다.
COOKIE_REQUIRED_KINDS = frozenset({Kind.STORY, Kind.HIGHLIGHT})

GALLERY_DL = "gallery-dl"
WEB = "instagram-web"
YT_DLP = "yt-dlp"

# yt-dlp 가 이미지 항목에서 내는 문구. 이걸 그냥 흘리면 "엔진을 업데이트하세요"라는
# 엉뚱한 안내가 나간다 — 업데이트로 해결되는 문제가 아니다.
_NO_VIDEO_FORMATS = re.compile(r"no video formats", re.I)

IMAGE_NEEDS_COOKIES = (
    "이미지 게시글은 쿠키가 필요합니다. yt-dlp 는 인스타 이미지를 추출하지 못하고"
    "(No video formats found), gallery-dl 은 쿠키 없이 접근할 수 없습니다. "
    "설정에서 인스타그램 쿠키를 등록해주세요."
)


def engine_order(has_cookies: bool) -> tuple[str, ...]:
    """엔진 순서.

    `instagram-web` 이 항상 먼저다 — 비로그인 GraphQL 을 직접 읽어 캐러셀의
    이미지·동영상을 **전부** 열거하는 유일한 경로다. yt-dlp 는 같은 응답을
    쓰면서도 이미지를 버리고, gallery-dl 은 익명 접근이 안 된다.

    쿠키가 있으면 gallery-dl 을 뒤에 둔다 — 비공개·스토리처럼 web 경로가
    게이팅되는 경우를 받쳐준다.
    """
    if has_cookies:
        return (WEB, GALLERY_DL, YT_DLP)
    return (WEB, YT_DLP)


def _clarify(exc: ArchGrabError, cookies: Path | None) -> ArchGrabError:
    """엔진 원문이 오해를 부르는 경우 메시지를 바꿔준다."""
    if cookies is None and _NO_VIDEO_FORMATS.search(exc.detail or ""):
        return ArchGrabError(ErrorCode.LOGIN_REQUIRED, IMAGE_NEEDS_COOKIES, detail=exc.detail)
    return exc


def _pick_format(item: MediaItem, wanted_id: str | None) -> FormatOption | None:
    """사용자가 고른 포맷, 없으면 첫 번째.

    포맷 목록은 엔진이 좋은 것부터 정렬해 내놓는다. 여기서 따로 고르지 않고
    formats[0] 을 쓰는 이유는, 프론트가 화면에 보여주는 것도 formats[0] 이기
    때문이다 — 둘이 같은 값을 쓰면 "보이는 것"과 "받는 것"이 어긋날 수 없다.
    """
    if wanted_id:
        for candidate in item.formats:
            if candidate.id == wanted_id:
                return candidate
    return item.formats[0] if item.formats else None


class InstagramExtractor:
    name = NAME

    # ---- 해석 ------------------------------------------------------------
    def probe(self, parsed: ParsedUrl) -> MediaInfo:
        with secrets_store.cookie_file(NAME) as cookies:
            self._require_cookies(parsed, cookies)
            failures: list[ArchGrabError] = []

            for engine in engine_order(cookies is not None):
                try:
                    if engine == WEB:
                        return instagram_web.probe(parsed, cookies)
                    if engine == GALLERY_DL:
                        entries, post = gallerydl_engine.dump(parsed.url, cookies)
                        return _to_media_info(parsed, entries, post, used_cookies=True)
                    return self._probe_ytdlp(parsed, cookies)
                except ArchGrabError as exc:
                    failures.append(_clarify(exc, cookies))

            raise failures[0]

    def _probe_ytdlp(self, parsed: ParsedUrl, cookies: Path | None) -> MediaInfo:
        info = ytdlp_engine.extract(parsed.url, cookies)
        media = ytdlp_engine.to_media_info(parsed, info, used_cookies=cookies is not None)

        # 전부 못 가져왔으면 보여줄 게 없다 — 이미지 전용 게시글이 이 경우다.
        if not media.items:
            raise ArchGrabError(ErrorCode.LOGIN_REQUIRED, IMAGE_NEEDS_COOKIES)

        # 일부만 가져왔으면 반드시 알린다. 조용히 버리면 사용자는 15개 중 3개만
        # 보고도 나머지가 사라진 줄 모른다.
        if media.missing_items:
            media.notice = (
                f"{media.missing_items}개 항목을 가져오지 못했습니다 (이미지 항목). "
                "쿠키를 등록하면 함께 받을 수 있습니다."
            )
        return media

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
            failures: list[ArchGrabError] = []

            for engine in engine_order(cookies is not None):
                try:
                    if engine == WEB:
                        return self._via_web(parsed, selection, dest, cookies, progress)
                    if engine == GALLERY_DL:
                        return self._via_gallerydl(parsed, selection, dest, cookies, progress)
                    return self._via_ytdlp(parsed, selection, dest, cookies, progress)
                except ArchGrabError as exc:
                    failures.append(_clarify(exc, cookies))

            raise failures[0]

    def _via_web(
        self,
        parsed: ParsedUrl,
        selection: Selection,
        dest: Path,
        cookies: Path | None,
        progress: ProgressCallback,
    ) -> list[Path]:
        """방금 해석한 결과를 재사용한다. 실패하면 다시 추출해 한 번 더 시도한다.

        예전에는 작업마다 GraphQL 을 다시 호출해서(페이지 fetch → ruling →
        graphql) 버튼을 누르고 2~4초를 그냥 기다렸다. 캐시된 MediaInfo 를 쓰면
        그 시간이 사라진다. 다만 담긴 CDN 주소는 서명·만료가 붙어 있으므로,
        받다가 실패하면 캐시를 버리고 신선한 주소로 재시도한다.
        """
        max_age = get_settings().resolve_cache_seconds

        for attempt in (0, 1):
            media = None if attempt else self._cached_media(parsed, cookies, max_age)
            if media is None:
                media = instagram_web.probe(parsed, cookies)
                media_cache.put(parsed.cache_key, media)

            pairs = self._pairs_for(parsed, media, selection)
            if not pairs:
                raise ArchGrabError(ErrorCode.ENGINE_FAILED, "내려받을 포맷을 찾지 못했습니다.")

            try:
                return _fetch_pairs(pairs, dest, cookies, progress)
            except ArchGrabError:
                if attempt:
                    raise
                # 만료된 주소였을 수 있다 — 캐시를 버리고 다시 추출한다
                media_cache.invalidate(parsed.cache_key)

        raise ArchGrabError(ErrorCode.ENGINE_FAILED)

    @staticmethod
    def _cached_media(parsed: ParsedUrl, cookies: Path | None, max_age: float) -> MediaInfo | None:
        cached = media_cache.get(parsed.cache_key, max_age)
        if cached is None:
            return None
        # 쿠키 유무가 달라지면 추출 결과도 달라진다 (비공개·스토리)
        if cached.used_cookies != (cookies is not None):
            return None
        # 다른 엔진이 담아둔 결과는 url 이 없을 수 있다
        if cached.engine != instagram_web.NAME:
            return None
        return cached

    @staticmethod
    def _pairs_for(
        parsed: ParsedUrl, media: MediaInfo, selection: Selection
    ) -> list[tuple[str, str]]:
        wanted = [item for item in media.items if selection.wants(item.id)] or media.items
        # 작업에 담긴 개수가 아니라 게시글의 항목 수로 판단한다. 15장 중 한 장만
        # 받아도 번호가 붙어야 여러 번 받았을 때 파일명이 겹치지 않는다.
        multiple = len(media.items) > 1

        pairs: list[tuple[str, str]] = []
        for item in wanted:
            chosen = _pick_format(item, selection.format_for(item.id))
            if chosen is None or not chosen.url:
                continue
            pairs.append((
                _item_filename(parsed, media, item, chosen, numbered=multiple),
                chosen.url,
            ))
        return pairs

    def _via_gallerydl(
        self,
        parsed: ParsedUrl,
        selection: Selection,
        dest: Path,
        cookies: Path | None,
        progress: ProgressCallback,
    ) -> list[Path]:
        # 서명 URL 은 시간이 지나면 만료되므로 작업 시점에 다시 추출한다
        entries, post = gallerydl_engine.dump(parsed.url, cookies)
        chosen = [
            (index, entry) for index, entry in enumerate(entries) if selection.wants(str(index))
        ] or list(enumerate(entries))

        multiple = len(chosen) > 1
        pairs = [
            (_gallery_filename(parsed, entry, post, index=index, numbered=multiple), entry.url)
            for index, entry in chosen
        ]
        return _fetch_pairs(pairs, dest, cookies, progress)

    def _via_ytdlp(
        self,
        parsed: ParsedUrl,
        selection: Selection,
        dest: Path,
        cookies: Path | None,
        progress: ProgressCallback,
    ) -> list[Path]:
        info = ytdlp_engine.extract(parsed.url, cookies)
        media = ytdlp_engine.to_media_info(parsed, info, used_cookies=cookies is not None)

        wanted = [item for item in media.items if selection.wants(item.id)] or media.items
        targets: list[tuple[MediaItem, FormatOption]] = []
        for item in wanted:
            chosen = _pick_format(item, selection.format_for(item.id))
            if chosen is not None:
                targets.append((item, chosen))

        if not targets:
            raise ArchGrabError(ErrorCode.ENGINE_FAILED, "내려받을 포맷을 찾지 못했습니다.")

        # 부분 스트림(영상만/음성만)이거나 직접 받을 수 없으면 yt-dlp 에 맡긴다.
        # needs_mux 를 꼭 봐야 한다 — URL 이 https 라서 직접 받을 수는 있지만
        # 그것만 받으면 음성이 빠진 파일이 나온다.
        needs_engine = [
            (item, fmt) for item, fmt in targets
            if fmt.needs_mux or not fmt.directly_fetchable
        ]
        if needs_engine:
            # 고른 영상 스트림에 최고 음성을 덧붙인다. 합치기는 스트림 복사만 한다.
            chosen_id = needs_engine[0][1].id
            return ytdlp_engine.download(
                parsed.url, dest, selection=selection, cookies=cookies,
                progress=progress,
                format_spec=f"{chosen_id}+bestaudio/{chosen_id}/b",
                # yt-dlp 가 받더라도 파일명 규칙은 우리 것을 쓴다
                outtmpl=_outtmpl(parsed, media),
            )

        multiple = len(targets) > 1
        pairs = [
            (
                _item_filename(parsed, media, item, fmt, numbered=multiple),
                str(fmt.url),
            )
            for item, fmt in targets
        ]
        return _fetch_pairs(pairs, dest, cookies, progress)

    @staticmethod
    def _require_cookies(parsed: ParsedUrl, cookies: Path | None) -> None:
        if cookies is None and parsed.kind in COOKIE_REQUIRED_KINDS:
            raise ArchGrabError(
                ErrorCode.LOGIN_REQUIRED,
                "스토리는 로그인한 사용자에게만 보입니다. 설정에서 인스타그램 쿠키를 등록해주세요.",
            )


# ---- 공통 내려받기 --------------------------------------------------------

def _fetch_pairs(
    pairs: list[tuple[str, str]],
    dest: Path,
    cookies: Path | None,
    progress: ProgressCallback,
) -> list[Path]:
    """(파일명, 주소) 목록을 순서대로 받는다. 두 엔진이 이 경로를 공유한다."""
    event = ProgressEvent(count=len(pairs))
    paths: list[Path] = []

    for position, (name, url) in enumerate(pairs, start=1):
        target = dest / name
        event.index = position
        event.current = name

        def on_bytes(done: int, total: int | None, _event: ProgressEvent = event) -> None:
            _event.done_bytes = done
            _event.total_bytes = total
            progress(_event)

        fetcher.fetch_to_file(url, target, referer=REFERER, cookies=cookies, progress=on_bytes)
        paths.append(target)

    return paths


# ---- 파일명 --------------------------------------------------------------

def _gallery_filename(
    parsed: ParsedUrl, entry: GalleryEntry, post: dict, *, index: int, numbered: bool
) -> str:
    meta = post or entry.meta
    username = _first(meta, "username", "owner_username") or parsed.username or "unknown"
    key = parsed.key or _first(entry.meta, "post_shortcode", "shortcode") or "item"
    suffix = f"_{index + 1}" if numbered else ""
    return safe_name(f"instagram_{username}_{key}{suffix}.{entry.extension}")


def _outtmpl(parsed: ParsedUrl, media: MediaInfo) -> str:
    """yt-dlp 출력 템플릿. % 는 템플릿 문법이라 사용자 값에서 이스케이프한다."""
    username = (media.uploader or parsed.username or "unknown").replace("%", "%%")
    key = (parsed.key or media.key or "item").replace("%", "%%")
    stem = safe_name(f"instagram_{username}_{key}", fallback="instagram")
    return f"{stem}.%(ext)s"


def _item_filename(
    parsed: ParsedUrl,
    media: MediaInfo,
    item: MediaItem,
    fmt: FormatOption,
    *,
    numbered: bool,
) -> str:
    username = media.uploader or parsed.username or "unknown"
    key = parsed.key or media.key or "item"
    suffix = f"_{item.index + 1}" if numbered else ""
    return safe_name(f"instagram_{username}_{key}{suffix}.{fmt.ext}")


# ---- gallery-dl 결과 정규화 ------------------------------------------------

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
                        url=entry.url,
                        protocol="https",
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
        engine=GALLERY_DL,
        used_cookies=used_cookies,
    )


extractor = InstagramExtractor()
