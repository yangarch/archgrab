"""yt-dlp 어댑터 — 동영상 주력, 인스타에서는 gallery-dl 실패 시 폴백.

라이브러리로 직접 호출하므로 프로세스 spawn 과 문자열 파싱이 없다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yt_dlp
from yt_dlp.utils import DownloadError, ExtractorError

from app.config import get_settings
from app.core.errors import ErrorCode, ArchGrabError, from_engine_error
from app.core.models import FormatOption, MediaInfo, MediaItem
from app.core.security import mask_secrets
from app.core.url import ParsedUrl
from app.extractors.base import ProgressCallback, ProgressEvent, Selection

NAME = "yt-dlp"


def version() -> str:
    return yt_dlp.version.__version__


def _base_opts(cookies: Path | None) -> dict[str, Any]:
    settings = get_settings()
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": False,      # 캐러셀은 playlist 로 온다
        "socket_timeout": 30,
        "retries": 3,
        "consoletitle": False,
        "nocheckcertificate": False,
    }
    if cookies is not None:
        opts["cookiefile"] = str(cookies)
    if settings.proxy:
        opts["proxy"] = settings.proxy
    return opts


def _wrap_error(exc: Exception) -> ArchGrabError:
    return from_engine_error(mask_secrets(str(exc)))


def extract(url: str, cookies: Path | None = None) -> dict[str, Any]:
    """메타데이터만 — download=False."""
    try:
        with yt_dlp.YoutubeDL(_base_opts(cookies)) as ydl:
            info = ydl.extract_info(url, download=False)
    except (DownloadError, ExtractorError) as exc:
        raise _wrap_error(exc) from exc
    except Exception as exc:  # yt-dlp 는 별별 예외를 올린다
        raise ArchGrabError(ErrorCode.ENGINE_FAILED, detail=mask_secrets(str(exc))) from exc
    if not info:
        raise ArchGrabError(ErrorCode.NOT_FOUND)
    return info


IMAGE_EXTENSIONS = frozenset({"jpg", "jpeg", "png", "webp", "heic", "avif"})
STREAMING_PROTOCOLS = ("m3u8", "dash", "mpd", "ism")


def _ext_from_url(url: str) -> str:
    tail = url.split("?")[0].rsplit(".", 1)
    return tail[-1].lower() if len(tail) == 2 and len(tail[-1]) <= 5 else "jpg"


def _real_formats(entry: dict[str, Any]) -> list[FormatOption]:
    """yt-dlp 가 준 재생 가능한 스트림만. 스토리보드·더미는 버린다."""
    options: list[FormatOption] = []
    for fmt in entry.get("formats") or []:
        ext = str(fmt.get("ext") or "")
        url = fmt.get("url")
        # 스토리보드·더미만 버린다. 코덱 정보 유무로 판단하면 안 된다 —
        # 인스타의 progressive mp4(video_versions)는 영상+음성이 함께 있는데도
        # vcodec/acodec 을 둘 다 보고하지 않는다. 그걸 버렸다가 DASH 영상전용을
        # 받아 무음 파일이 나온 적이 있다.
        if ext in {"mhtml", "none"} or not url:
            continue
        vcodec, acodec = fmt.get("vcodec"), fmt.get("acodec")
        size = fmt.get("filesize")
        options.append(
            FormatOption(
                id=str(fmt.get("format_id") or ext),
                ext=ext or "bin",
                width=fmt.get("width"),
                height=fmt.get("height"),
                fps=fmt.get("fps"),
                filesize=size or fmt.get("filesize_approx"),
                filesize_approx=size is None,
                vcodec=vcodec,
                acodec=acodec,
                # 인스타 progressive 포맷은 해상도·용량을 안 준다. 라벨이 죄다
                # "mp4" 로 같아 보이지 않도록 최소한 id 로 구분해준다.
                note=fmt.get("format_note") or (
                    None if fmt.get("width") else f"#{fmt.get('format_id')}"
                ),
                # 영상만 있는 스트림은 음성과 합쳐야 한다 (무손실 mux)
                needs_mux=bool(vcodec and vcodec != "none" and acodec in {None, "none"}),
                url=fmt.get("url"),
                protocol=fmt.get("protocol"),
            )
        )
    return options


def _image_format(entry: dict[str, Any]) -> FormatOption | None:
    """이미지 게시글용 — yt-dlp 는 이미지를 formats 가 아니라 thumbnails 에 담는다.

    formats 는 video_versions·DASH 에서만 만들어지므로 이미지 게시글에는 내려받을
    포맷이 없다. 대신 image_versions2 후보가 thumbnails 로 오고, 그 목록에는 원본
    해상도까지 들어 있다. 가장 큰 후보를 원본으로 집는다.
    """
    candidates = [
        t for t in (entry.get("thumbnails") or [])
        if isinstance(t, dict) and str(t.get("url") or "").startswith(("http://", "https://"))
    ]
    if not candidates:
        return None

    best = max(candidates, key=lambda t: (t.get("width") or 0) * (t.get("height") or 0))
    url = str(best["url"])
    return FormatOption(
        id="image",
        ext=_ext_from_url(url),
        width=best.get("width"),
        height=best.get("height"),
        note="원본 이미지",
        url=url,
        protocol="https",
    )


def _is_audio_only(option: FormatOption) -> bool:
    return option.vcodec == "none"


def _rank(option: FormatOption) -> tuple:
    """정렬 키 — 좋은 것이 먼저. 화면의 formats[0] 이 실제로 받는 것과 같아야 한다.

    해상도를 가장 앞에 둔다. 최고 해상도가 DASH 영상전용으로만 제공되는 경우가
    있는데(인스타에서 흔하다), 그때도 그걸 골라야 한다 — 다운로드 단계에서
    음성을 무손실로 합친다.
    """
    return (
        not _is_audio_only(option),                    # 음성 전용은 맨 뒤
        (option.width or 0) * (option.height or 0),    # 해상도 우선
        option.directly_fetchable,                     # 같은 해상도면 직접 받을 수 있는 쪽
        not option.needs_mux,                          # 그다음 완결 포맷
        option.filesize or 0,
    )


def _formats(entry: dict[str, Any]) -> list[FormatOption]:
    options = _real_formats(entry)
    if options:
        return sorted(options, key=_rank, reverse=True)

    image = _image_format(entry)
    if image:
        return [image]

    # 단일 URL 항목 (포맷 목록 없이 url 만 오는 경우)
    url = entry.get("url")
    if url:
        return [
            FormatOption(
                id=str(entry.get("format_id") or "original"),
                ext=str(entry.get("ext") or _ext_from_url(str(url))),
                width=entry.get("width"),
                height=entry.get("height"),
                filesize=entry.get("filesize") or entry.get("filesize_approx"),
                filesize_approx=entry.get("filesize") is None,
                url=str(url),
                protocol=entry.get("protocol") or "https",
            )
        ]
    return []


def _media_type(entry: dict[str, Any], formats: list[FormatOption]) -> str:
    """포맷을 먼저 보고 판정한다 — 이게 실제로 무엇을 받게 되는지와 일치한다."""
    if any(f.vcodec and f.vcodec != "none" for f in formats):
        return "video"
    if formats and all(f.ext in IMAGE_EXTENSIONS for f in formats):
        return "image"
    if any(f.acodec and f.acodec != "none" for f in formats):
        return "audio"
    if entry.get("duration"):
        return "video"
    return "image" if str(entry.get("ext", "")).lower() in IMAGE_EXTENSIONS else "video"


def to_media_info(parsed: ParsedUrl, info: dict[str, Any], *, used_cookies: bool) -> MediaInfo:
    entries = info.get("entries")
    if isinstance(entries, list):
        items_source: list[dict[str, Any]] = [e for e in entries if isinstance(e, dict)]
        # 추출에 실패한 항목은 None 으로 온다. 인스타 카러셀의 이미지 항목이
        # 대표적이다 — yt-dlp 는 "No video formats found!" 로 실패한다.
        missing = len(entries) - len(items_source)
    else:
        items_source = [info]
        missing = 0

    items = []
    for index, entry in enumerate(items_source):
        formats = _formats(entry)
        items.append(
            MediaItem(
                id=str(index),
                index=index,
                type=_media_type(entry, formats),  # type: ignore[arg-type]
                title=entry.get("title") or entry.get("description"),
                thumbnail=entry.get("thumbnail"),
                duration=entry.get("duration"),
                width=entry.get("width"),
                height=entry.get("height"),
                formats=formats,
            )
        )

    return MediaInfo(
        platform=parsed.platform,
        kind=parsed.kind,
        source_url=parsed.url,
        key=parsed.key,
        title=info.get("title") or info.get("description"),
        uploader=info.get("uploader") or info.get("uploader_id") or info.get("channel"),
        uploader_url=info.get("uploader_url") or info.get("channel_url"),
        description=info.get("description"),
        items=items,
        engine=NAME,
        used_cookies=used_cookies,
        missing_items=missing,
    )


def download(
    url: str,
    dest: Path,
    *,
    selection: Selection,
    cookies: Path | None = None,
    progress: ProgressCallback | None = None,
    outtmpl: str = "%(title).80B [%(id)s].%(ext)s",
    format_spec: str | None = None,
) -> list[Path]:
    """dest 에 받은 파일 경로 목록. 코덱 변환은 하지 않는다 (mux 만)."""
    produced: list[Path] = []
    event = ProgressEvent()

    def hook(status: dict[str, Any]) -> None:
        if status.get("status") == "downloading" and progress:
            event.done_bytes = int(status.get("downloaded_bytes") or 0)
            total = status.get("total_bytes") or status.get("total_bytes_estimate")
            event.total_bytes = int(total) if total else None
            name = status.get("filename") or ""
            event.current = Path(name).name or None
            progress(event)
        elif status.get("status") == "finished":
            name = status.get("filename")
            if name:
                produced.append(Path(name))

    opts = _base_opts(cookies)
    opts.update(
        {
            "paths": {"home": str(dest)},
            "outtmpl": outtmpl,
            "progress_hooks": [hook],
            "noplaylist": False,
            # 최고 화질 원본. bv*+ba 는 컨테이너만 합치고 코덱은 건드리지 않는다.
            # format_spec 이 오면 사용자가 고른 포맷에 음성만 덧붙인다.
            "format": (
                "bestaudio/best" if selection.audio_only
                else format_spec or "bv*+ba/b"
            ),
            "merge_output_format": "mp4",
            # 재인코딩 금지 — 합칠 때도 스트림 복사만.
            "postprocessor_args": {"merger": ["-c", "copy"]},
        }
    )

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
    except (DownloadError, ExtractorError) as exc:
        raise _wrap_error(exc) from exc

    # mux 된 결과물만 남기고 중간 파일은 제외한다
    final = [p for p in dest.iterdir() if p.is_file() and not p.name.endswith(".part")]
    return sorted(final) if final else sorted(set(produced))
