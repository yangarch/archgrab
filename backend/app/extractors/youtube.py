"""유튜브 — yt-dlp 기반. 핵심 작업은 **포맷 정리**다.

앞선 두 플랫폼과 성격이 다르다. 인스타·X 는 사실상 원본 하나였는데 유튜브는
한 영상에 포맷이 44개씩 온다. 그대로 내보내면 화면이 쓸 수 없게 된다.

실측으로 확인한 것 (dQw4w9WgXcQ):
- **완결(영상+음성) 포맷이 0개**다. 37개가 영상전용, 5개가 음성전용.
  즉 유튜브는 mux 가 선택이 아니라 필수다.
- 같은 해상도가 webm / mp4 / HLS 로 3번씩 중복된다.
- 4K 기준 webm(vp9) 342MB vs mp4(av01) 229MB — 컨테이너를 고르지 않으면
  더 크고 호환성도 낮은 쪽이 기본이 된다.

그래서 해상도마다 하나씩만 남기고, 같은 해상도면 직접 받을 수 있는 mp4 를
고른다. 음성전용은 "오디오만" 선택지로 하나 붙인다.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.config import get_settings
from app.core import secrets_store
from app.core.errors import ArchGrabError, ErrorCode
from app.core.models import FormatOption, MediaInfo
from app.core.url import ParsedUrl
from app.extractors import ytdlp_engine
from app.extractors.base import ProgressCallback, Selection, noop_progress

NAME = "youtube"
PREFIX = "youtube"

AUDIO_NOTE = "오디오만"

# 유튜브가 데이터센터 IP 를 막을 때 내는 문구. 집에서는 되는데 서버에서만
# 실패하는 증상이 이것이다. 쿠키로도 풀리지만 원인은 로그인이 아니라 IP 라서,
# 그냥 "쿠키를 등록하세요" 라고만 하면 오해를 부른다.
_BOT_CHECK = re.compile(r"sign in to confirm|not a bot|confirm you'?re not", re.I)

BOT_CHECK_MESSAGE = (
    "유튜브가 이 서버의 IP 를 봇으로 보고 차단했습니다. 데이터센터 IP 에서 자주 생깁니다. "
    "설정에서 유튜브 쿠키를 등록하거나, ARCHGRAB_PROXY 로 다른 IP 를 경유하세요."
)

DEGRADED_NOTICE = (
    "유튜브 봇 감지를 피하려고 대체 클라이언트({client})로 받았습니다. "
    "이 경로는 화질이 크게 제한됩니다(대개 360p). 원래 화질로 받으려면 "
    "유튜브 쿠키를 등록하거나 프록시를 설정하세요."
)


def _is_audio_only(fmt: FormatOption) -> bool:
    return fmt.vcodec == "none" and bool(fmt.acodec) and fmt.acodec != "none"


def _has_video(fmt: FormatOption) -> bool:
    return bool(fmt.vcodec) and fmt.vcodec != "none"


def _video_rank(fmt: FormatOption) -> tuple:
    """같은 해상도 안에서 무엇을 남길지.

    직접 받을 수 있는 쪽(HLS 가 아닌) → mp4 → 큰 파일 순. mp4 를 앞에 두는 이유는
    같은 4K 에서 webm(vp9) 342MB 보다 mp4(av01) 229MB 가 더 작고 호환성도 좋기
    때문이다. 화질을 깎는 선택이 아니라 코덱 효율 차이다.
    """
    return (fmt.directly_fetchable, fmt.ext == "mp4", fmt.filesize or 0)


def pick_audio(formats: list[FormatOption], *, container: str | None = None) -> FormatOption | None:
    """합칠 음성을 고른다.

    mp4 에는 m4a(AAC)를 넣어야 한다. yt-dlp 의 bestaudio 는 품질만 보고 opus 를
    고르는데, opus-in-mp4 는 QuickTime·iOS 기본 재생기가 열지 못하는 경우가 많다.
    실측에서 그렇게 만들어졌다 — 받아지긴 하지만 재생이 안 되면 의미가 없다.
    """
    audio = [f for f in formats if _is_audio_only(f)]
    if not audio:
        return None
    preferred = "m4a" if container == "mp4" else None
    return max(
        audio,
        key=lambda f: (f.directly_fetchable, f.ext == preferred, f.filesize or 0),
    )


def group_formats(formats: list[FormatOption]) -> list[FormatOption]:
    """해상도마다 하나씩 + 오디오 하나. 44개를 고를 수 있는 목록으로 줄인다."""
    best_by_height: dict[int, FormatOption] = {}
    for fmt in formats:
        if not _has_video(fmt):
            continue
        height = fmt.height or 0
        if height == 0:
            continue
        current = best_by_height.get(height)
        if current is None or _video_rank(fmt) > _video_rank(current):
            best_by_height[height] = fmt

    grouped: list[FormatOption] = []
    for height in sorted(best_by_height, reverse=True):
        video = best_by_height[height]
        audio = pick_audio(formats, container=video.ext)
        # 표시 용량에 합쳐질 음성을 더한다. 영상전용 크기만 보여주면 실제
        # 받아지는 파일과 어긋난다(실측: 8.0MB 표시 → 11.8MB 파일).
        if video.needs_mux and video.filesize and audio and audio.filesize:
            video = video.model_copy(
                update={"filesize": video.filesize + audio.filesize, "filesize_approx": True}
            )
        grouped.append(video)

    best_audio = pick_audio(formats)
    if best_audio:
        # 라벨에서 "오디오만" 이 바로 보이게 한다 — 실수로 고르면 영상이 없다
        grouped.append(best_audio.model_copy(update={"note": AUDIO_NOTE}))

    return grouped


def to_media_info(parsed: ParsedUrl, raw: dict, *, used_cookies: bool) -> MediaInfo:
    info = ytdlp_engine.to_media_info(parsed, raw, used_cookies=used_cookies)
    for item in info.items:
        grouped = group_formats(item.formats)
        if grouped:
            item.formats = grouped
            item.width = grouped[0].width
            item.height = grouped[0].height
    info.engine = NAME
    return info


def _client_sets() -> tuple[list[str] | None, list[list[str]]]:
    """(먼저 쓸 클라이언트, 실패 시 순서대로 시도할 후보들)."""
    settings = get_settings()
    primary = settings.client_list(settings.youtube_player_clients) or None
    fallbacks = [[c] for c in settings.client_list(settings.youtube_fallback_clients)]
    if primary:
        fallbacks = [f for f in fallbacks if f[0] not in primary]
    return primary, fallbacks


def _extract(parsed: ParsedUrl, cookies: Path | None) -> tuple[dict, str | None]:
    """(추출 결과, 폴백에 쓴 클라이언트).

    봇 감지에 걸리면 다른 player_client 로 바꿔 다시 시도한다. 다만 실측상
    동작하는 대체 클라이언트는 android 계열뿐이고 360p 로 제한된다 — 구제는
    되지만 화질을 깎으므로, 쓰였다는 사실을 호출한 쪽에 돌려준다.
    """
    primary, fallbacks = _client_sets()
    try:
        return ytdlp_engine.extract(parsed.url, cookies, player_clients=primary), None
    except ArchGrabError as exc:
        if not _BOT_CHECK.search(exc.detail or ""):
            raise
        for clients in fallbacks:
            try:
                raw = ytdlp_engine.extract(parsed.url, cookies, player_clients=clients)
            except ArchGrabError:
                continue
            return raw, clients[0]
        raise ArchGrabError(
            ErrorCode.LOGIN_REQUIRED, BOT_CHECK_MESSAGE, detail=exc.detail
        ) from exc


class YouTubeExtractor:
    name = NAME

    def probe(self, parsed: ParsedUrl) -> MediaInfo:
        with secrets_store.cookie_file(NAME) as cookies:
            raw, degraded = _extract(parsed, cookies)
            info = to_media_info(parsed, raw, used_cookies=cookies is not None)
            if degraded:
                # 조용히 360p 를 주지 않는다 — 화면에 이유를 띄운다
                info.notice = DEGRADED_NOTICE.format(client=degraded)
            return info

    def download(
        self,
        parsed: ParsedUrl,
        selection: Selection,
        dest: Path,
        progress: ProgressCallback = noop_progress,
    ) -> list[Path]:
        with secrets_store.cookie_file(NAME) as cookies:
            # 유튜브는 완결 포맷이 없어 항상 mux 가 필요하다. yt-dlp 에 맡기고
            # 합칠 때는 스트림 복사만 한다(-c copy) — 재인코딩 없음.
            chosen = selection.format_for("0")
            if selection.audio_only:
                spec = None                      # ytdlp_engine 이 bestaudio 를 고른다
            elif chosen:
                # mp4 에는 m4a 를 우선 붙인다 — opus-in-mp4 는 QuickTime·iOS 가
                # 열지 못하는 경우가 많다. 없으면 아무 음성이라도 붙인다.
                spec = f"{chosen}+bestaudio[ext=m4a]/{chosen}+bestaudio/{chosen}/b"
            else:
                spec = "bv*[ext=mp4]+ba[ext=m4a]/bv*+ba/b"

            primary, _ = _client_sets()
            paths = ytdlp_engine.download(
                parsed.url,
                dest,
                selection=selection,
                cookies=cookies,
                progress=progress,
                format_spec=spec,
                outtmpl=_outtmpl(parsed),
                player_clients=primary,
            )
            if not paths:
                raise ArchGrabError(ErrorCode.ENGINE_FAILED, "내려받은 파일이 없습니다.")
            return paths


def _outtmpl(parsed: ParsedUrl) -> str:
    # 제목은 길고 특수문자가 많아 파일명 규칙에 넣지 않는다. 영상 id 로 충분히 고유하다.
    return f"{PREFIX}_%(uploader).40B_{parsed.key}.%(ext)s"


extractor = YouTubeExtractor()
