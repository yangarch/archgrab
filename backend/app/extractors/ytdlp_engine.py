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


def _media_type(entry: dict[str, Any]) -> str:
    if entry.get("_type") == "url" and entry.get("ext") in {"jpg", "jpeg", "png", "webp", "heic"}:
        return "image"
    vcodec = entry.get("vcodec")
    acodec = entry.get("acodec")
    if entry.get("duration") or (vcodec and vcodec != "none"):
        return "video"
    if acodec and acodec != "none":
        return "audio"
    if str(entry.get("ext", "")).lower() in {"jpg", "jpeg", "png", "webp", "heic"}:
        return "image"
    return "video"


def _formats(entry: dict[str, Any]) -> list[FormatOption]:
    raw = entry.get("formats") or []
    options: list[FormatOption] = []
    for fmt in raw:
        ext = str(fmt.get("ext") or "")
        if ext in {"mhtml", "none"}:          # 스토리보드·더미
            continue
        vcodec = fmt.get("vcodec")
        acodec = fmt.get("acodec")
        if vcodec in {None, "none"} and acodec in {None, "none"}:
            continue
        size = fmt.get("filesize")
        approx = size is None
        options.append(
            FormatOption(
                id=str(fmt.get("format_id") or ext),
                ext=ext or "bin",
                width=fmt.get("width"),
                height=fmt.get("height"),
                fps=fmt.get("fps"),
                filesize=size or fmt.get("filesize_approx"),
                filesize_approx=approx,
                vcodec=vcodec,
                acodec=acodec,
                note=fmt.get("format_note"),
                # 영상만 있는 스트림은 음성과 합쳐야 한다 (무손실 mux)
                needs_mux=bool(vcodec and vcodec != "none" and acodec in {None, "none"}),
            )
        )
    if not options:
        # 단일 URL 항목 (인스타 이미지 등)
        options.append(
            FormatOption(
                id=str(entry.get("format_id") or "original"),
                ext=str(entry.get("ext") or "bin"),
                width=entry.get("width"),
                height=entry.get("height"),
                filesize=entry.get("filesize") or entry.get("filesize_approx"),
                filesize_approx=entry.get("filesize") is None,
            )
        )
    return options


def to_media_info(parsed: ParsedUrl, info: dict[str, Any], *, used_cookies: bool) -> MediaInfo:
    entries = info.get("entries")
    items_source: list[dict[str, Any]] = (
        [e for e in entries if isinstance(e, dict)] if isinstance(entries, list) else [info]
    )

    items = [
        MediaItem(
            id=str(index),
            index=index,
            type=_media_type(entry),  # type: ignore[arg-type]
            title=entry.get("title") or entry.get("description"),
            thumbnail=entry.get("thumbnail"),
            duration=entry.get("duration"),
            width=entry.get("width"),
            height=entry.get("height"),
            formats=_formats(entry),
        )
        for index, entry in enumerate(items_source)
    ]

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
    )


def download(
    url: str,
    dest: Path,
    *,
    selection: Selection,
    cookies: Path | None = None,
    progress: ProgressCallback | None = None,
    outtmpl: str = "%(title).80B [%(id)s].%(ext)s",
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
            "format": "bestaudio/best" if selection.audio_only else "bv*+ba/b",
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
