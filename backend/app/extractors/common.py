"""추출기들이 공유하는 부분.

플랫폼이 늘어나도 내려받기·파일명 규칙은 한 곳에서 유지한다.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from pathlib import Path

from app.core.errors import ArchGrabError, ErrorCode
from app.core.models import FormatOption, MediaInfo, MediaItem
from app.core.url import Kind, ParsedUrl
from app.extractors.base import ProgressCallback, ProgressEvent
from app.media import fetcher
from app.media.storage import safe_name


def reject_unsupported_kinds(parsed: ParsedUrl, messages: Mapping[Kind, str]) -> None:
    """지원하지 않는 종류면 엔진을 때리기 전에 분명하게 거절한다.

    파서는 주소 모양만 보므로 프로필·재생목록처럼 **파싱은 되지만 처리기가 없는**
    종류를 통과시킨다. 그대로 엔진에 넘기면 엉뚱한 실패가 나고, 그 문구가 오류
    분류기에서 잘못된 원인으로 접힌다. 실제로 겪은 두 경우:

    - 인스타 프로필 → 사용자명을 숏코드로 착각해 엉뚱한 media_id 가 만들어지고
      "비공개·삭제·제한… 쿠키를 등록하면 접근할 수 있습니다"가 나갔다. 쿠키를
      등록해도 안 되는데 사용자를 등록하러 보냈다.
    - 유튜브 재생목록 → yt-dlp 가 항목을 순회하다 볼 수 없는 영상 하나를 만나고
      "삭제되었거나 존재하지 않는 콘텐츠입니다"가 나갔다. 재생목록은 멀쩡했다.

    그래서 거절을 엔진 **앞**에 두고, 플랫폼마다 선언으로 남긴다. 새 플랫폼이
    같은 걸 빠뜨리지 않도록 이 한 곳에 모은다.
    """
    message = messages.get(parsed.kind)
    if message:
        raise ArchGrabError(ErrorCode.UNSUPPORTED, message)


def fetch_pairs(
    pairs: list[tuple[str, str]],
    dest: Path,
    cookies: Path | None,
    progress: ProgressCallback,
    *,
    referer: str | None = None,
) -> list[Path]:
    """(파일명, 주소) 목록을 순서대로 받는다.

    엔진이 무엇이든 실제 바이트는 이 경로로만 내려온다 — 진행률·파일명을 우리가
    통제하고 재인코딩이 끼어들 여지가 없다.
    """
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

        fetcher.fetch_to_file(url, target, referer=referer, cookies=cookies, progress=on_bytes)
        paths.append(target)

    return paths


def media_filename(
    prefix: str,
    parsed: ParsedUrl,
    media: MediaInfo,
    item: MediaItem,
    fmt: FormatOption,
    *,
    numbered: bool,
) -> str:
    """`{플랫폼}_{작성자}_{키}[_{n}].{확장자}`

    여러 항목이 있는 게시글이면 한 개만 받아도 번호를 붙인다 — 따로따로 여러 번
    받았을 때 다운로드 폴더에서 이름이 겹치지 않게.
    """
    username = media.uploader or parsed.username or "unknown"
    key = parsed.key or media.key or "item"
    suffix = f"_{item.index + 1}" if numbered else ""
    return safe_name(f"{prefix}_{username}_{key}{suffix}.{fmt.ext}")


def first_text(meta: dict, *keys: str) -> str | None:
    for key in keys:
        value = meta.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def parse_timestamp(raw: object) -> datetime | None:
    """엔진마다 date 를 문자열로도, 에포크로도 준다."""
    if isinstance(raw, str):
        for text in (raw.replace("Z", "+00:00"), raw):
            try:
                return datetime.fromisoformat(text)
            except ValueError:
                continue
        return None
    if isinstance(raw, int | float) and raw > 0:
        try:
            return datetime.fromtimestamp(raw)
        except (OSError, OverflowError, ValueError):
            return None
    return None
