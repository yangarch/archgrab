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

from datetime import datetime
from pathlib import Path

from app.core import secrets_store
from app.core.errors import ArchGrabError, ErrorCode
from app.core.models import FormatOption, MediaInfo, MediaItem
from app.core.url import Kind, ParsedUrl
from app.extractors import gallerydl_engine, ytdlp_engine
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
YT_DLP = "yt-dlp"


def engine_order(has_cookies: bool) -> tuple[str, ...]:
    """쿠키 유무로 엔진 순서를 정한다. 모듈 독스트링에 근거를 적어뒀다."""
    return (GALLERY_DL, YT_DLP) if has_cookies else (YT_DLP,)


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
                    if engine == GALLERY_DL:
                        entries, post = gallerydl_engine.dump(parsed.url, cookies)
                        return _to_media_info(parsed, entries, post, used_cookies=True)
                    info = ytdlp_engine.extract(parsed.url, cookies)
                    return ytdlp_engine.to_media_info(
                        parsed, info, used_cookies=cookies is not None
                    )
                except ArchGrabError as exc:
                    failures.append(exc)

            raise failures[0]

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
                    if engine == GALLERY_DL:
                        return self._via_gallerydl(parsed, selection, dest, cookies, progress)
                    return self._via_ytdlp(parsed, selection, dest, cookies, progress)
                except ArchGrabError as exc:
                    failures.append(exc)

            raise failures[0]

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
                _ytdlp_filename(parsed, media, item, fmt, numbered=multiple),
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


def _ytdlp_filename(
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
