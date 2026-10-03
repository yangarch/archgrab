"""스레드 비로그인 웹 클라이언트.

gallery-dl(1.32.12)과 yt-dlp(2026.08.19) **둘 다 스레드 추출기가 없다**(확인함).
그래서 직접 읽는다. 다행히 스레드는 메타의 같은 인프라라서 게시글 HTML 의
`<script type="application/json">` 블록에 인스타 비공개 API 와 **동일한** 구조가
들어 있다:

  media_type  1=이미지 2=동영상 8=캐러셀 19=텍스트 전용
  image_versions2.candidates[]  ← width/height 가 **있다** (인스타와 다른 점)
  video_versions[]              ← progressive mp4 (영상+음성)
  carousel_media[]              ← 항목별로 위 구조 반복

전제 조건은 인스타와 같다: **브라우저 TLS 지문 위장**(curl_cffi). 로그인은 필요
없다 — 공개 게시글은 쿠키 없이 받는다(확인함).

실측으로 확인한 함정 넷. 전부 코드로 막아둔다.

1. **게시글 1개 페이지에 답글 작성자들의 노드까지 섞여 온다.** 한 게시글에서
   16개 계정 25개 노드가 나왔고 그중 남의 답글 미디어가 6건이었다. "첫 미디어
   노드"나 "모든 미디어 노드"를 집으면 모르는 사람 사진을 받는다. 주소의 code 와
   정확히 일치하는 노드만 쓴다.
2. **없는 게시글도 HTTP 200 이다.** 404 가 오지 않는다. 일치 노드가 0개인 것이
   NOT_FOUND 신호다. 텍스트 전용 글과는 구분된다 — 그쪽은 노드가 있고 미디어만 없다.
3. **원본 이미지가 webp 로 온다.** Accept 헤더를 세 가지로 바꿔도 전부
   `image/webp` 였다. 인스타는 jpeg 다. 확장자를 URL 경로에서 뽑되 실제
   content-type 과 어긋나지 않게 webp 를 그대로 쓴다.
4. **동영상 노드의 image_versions2 는 썸네일뿐이다.** 최대 640x800 인데 실제
   영상은 1080x1350 이었다. 동영상은 video_versions 만 쓴다. 그리고 type
   101/102/103 은 실측에서 **바이트 수까지 같은 파일**이라 화질 선택지가 아니다.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from http.cookiejar import LoadError, MozillaCookieJar
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from app.config import get_settings
from app.core.errors import ArchGrabError, ErrorCode
from app.core.models import FormatOption, MediaInfo, MediaItem
from app.core.security import mask_secrets
from app.core.url import ParsedUrl

NAME = "threads-web"

MEDIA_IMAGE = 1
MEDIA_VIDEO = 2
MEDIA_CAROUSEL = 8
MEDIA_TEXT = 19

_JSON_BLOCK = re.compile(r'<script type="application/json"[^>]*>(.*?)</script>', re.S)
# stp 안의 크기 토큰. 예: p1080x1080, s640x640. 토큰이 없는 후보가 원본이다.
_SIZE_TOKEN = re.compile(r"[ps](\d+)x(\d+)")

TEXT_ONLY = "이 글에는 내려받을 미디어가 없습니다 (텍스트 전용)."


def is_available() -> bool:
    """curl_cffi 가 있는지. 없으면 이 경로 자체가 성립하지 않는다."""
    try:
        import curl_cffi  # noqa: F401
    except ImportError:
        return False
    return True


def post_url(code: str) -> str:
    """항상 `/t/{code}` 로 요청한다.

    주소에 적힌 사용자명은 장식이다 — 남의 사용자명을 붙여도 같은 게시글이
    내려온다(확인함). 사용자명을 쓰지 않으면 오타·불일치에 영향받지 않는다.
    """
    return f"https://www.threads.com/t/{code}"


def _session(cookies: Path | None):  # noqa: ANN202
    from curl_cffi import requests

    settings = get_settings()
    session = requests.Session(
        impersonate="chrome",
        timeout=settings.engine_timeout,
        proxy=settings.proxy,
    )
    if cookies is not None:
        jar = MozillaCookieJar(str(cookies))
        try:
            jar.load(ignore_discard=True, ignore_expires=True)
        except (OSError, LoadError):
            pass
        else:
            for cookie in jar:
                session.cookies.set(cookie.name, cookie.value, domain=cookie.domain or "")
    return session


def _fail(code: ErrorCode, detail: str | None = None) -> ArchGrabError:
    return ArchGrabError(code, detail=mask_secrets(detail) if detail else None)


def _walk(value: Any, code: str, found: list[dict[str, Any]]) -> None:
    """code 가 일치하는 노드만 모은다 (함정 1)."""
    if isinstance(value, dict):
        if value.get("code") == code and "media_type" in value:
            found.append(value)
        for child in value.values():
            _walk(child, code, found)
    elif isinstance(value, list):
        for child in value:
            _walk(child, code, found)


def _fetch_node(parsed: ParsedUrl, cookies: Path | None) -> dict[str, Any]:
    if not is_available():
        raise ArchGrabError(
            ErrorCode.ENGINE_FAILED,
            "curl_cffi 가 설치되지 않아 비로그인 접근을 쓸 수 없습니다. `make install` 을 실행해주세요.",
        )

    from curl_cffi import requests as curl_requests

    session = _session(cookies)
    try:
        page = session.get(post_url(parsed.key), allow_redirects=True)
        final = str(getattr(page, "url", "") or "")
        if "/login" in final or "accounts/login" in final:
            raise _fail(ErrorCode.LOGIN_REQUIRED, "게시글 페이지가 로그인으로 리다이렉트됨")
        if page.status_code == 404:
            raise _fail(ErrorCode.NOT_FOUND)
        if page.status_code >= 400:
            raise _fail(ErrorCode.ENGINE_FAILED, f"게시글 페이지 HTTP {page.status_code}")
        body = page.text
    except ArchGrabError:
        raise
    except curl_requests.errors.RequestsError as exc:
        raise _fail(ErrorCode.TIMEOUT, str(exc)) from exc
    except Exception as exc:  # curl_cffi 는 다양한 예외를 올린다
        raise _fail(ErrorCode.ENGINE_FAILED, str(exc)) from exc
    finally:
        session.close()

    return pick_node(body, parsed.key)


def pick_node(body: str, code: str) -> dict[str, Any]:
    """HTML 에서 해당 게시글의 노드 하나를 꺼낸다."""
    found: list[dict[str, Any]] = []
    for block in _JSON_BLOCK.findall(body):
        try:
            data = json.loads(block)
        except (ValueError, json.JSONDecodeError):
            continue
        _walk(data, code, found)

    if not found:
        # 함정 2: 없는 게시글도 200 이라 여기서만 구분된다. 비공개인지 삭제인지는
        # 응답으로 갈라지지 않으므로 둘 다 포함해 말한다.
        raise ArchGrabError(
            ErrorCode.NOT_FOUND,
            "게시글을 찾을 수 없습니다. 삭제되었거나 비공개 계정일 수 있습니다.",
        )

    # 같은 노드가 여러 블록에 중복되는 경우가 있다. 미디어를 가진 쪽을 고른다.
    return max(found, key=_media_weight)


def _media_weight(node: dict[str, Any]) -> int:
    carousel = node.get("carousel_media")
    if isinstance(carousel, list):
        return 1000 + len(carousel)
    if node.get("video_versions"):
        return 100
    if ((node.get("image_versions2") or {}).get("candidates")):
        return 10
    return 0


# ---- 정규화 --------------------------------------------------------------

def _original_candidate(node: dict[str, Any]) -> dict[str, Any] | None:
    """stp 에 크기 토큰이 없는 후보가 원본이다.

    실측: 항목마다 토큰 없는 후보가 **정확히 1개**였고, 이미지 항목에서는 그
    크기가 노드의 original_width/height 와 정확히 일치했다(7장 전부). 나머지
    후보 14개 중 7개는 크롭(`c0.270.2160.2160a`)이라 면적만 보고 고르면 잘린
    이미지를 집을 수 있다.
    """
    candidates = ((node.get("image_versions2") or {}).get("candidates")) or []
    best: dict[str, Any] | None = None
    best_pixels = -1

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        url = candidate.get("url")
        if not isinstance(url, str) or not url.startswith("http"):
            continue
        stp = (parse_qs(urlparse(url).query).get("stp") or [""])[0]
        match = _SIZE_TOKEN.search(stp)
        if match:
            pixels = int(match.group(1)) * int(match.group(2))
        else:
            pixels = 1 << 40  # 크기 토큰 없음 = 원본
        if pixels > best_pixels:
            best_pixels, best = pixels, candidate

    return best


def _extension(url: str, fallback: str) -> str:
    tail = urlparse(url).path.rsplit(".", 1)
    if len(tail) == 2 and 1 <= len(tail[-1]) <= 5 and tail[-1].isalnum():
        return tail[-1].lower()
    return fallback


def _image_formats(node: dict[str, Any]) -> list[FormatOption]:
    candidate = _original_candidate(node)
    if candidate is None:
        return []
    url = str(candidate["url"])
    return [
        FormatOption(
            id="original",
            # 함정 3: 스레드 원본은 webp 다. 경로의 확장자를 그대로 쓴다.
            ext=_extension(url, "webp"),
            # 후보가 직접 들고 있는 크기다 (실측에서 original_* 와 일치).
            width=candidate.get("width") or node.get("original_width"),
            height=candidate.get("height") or node.get("original_height"),
            note="원본",
            url=url,
            protocol="https",
        )
    ]


def _video_formats(node: dict[str, Any]) -> list[FormatOption]:
    """video_versions 는 progressive mp4 다 (mux 불필요).

    **해상도를 주장하지 않는다.** 응답이 영상 렌디션 크기를 주지 않고, 노드의
    original_width/height 는 업로드 원본이라 서빙되는 파일과 다를 수 있다
    (인스타에서 1080x1440 이라 보고된 항목의 실제 파일이 720x960 이었다).
    화면에 적으면 "보이는 것"과 "받는 것"이 어긋난다.

    type 101/102/103 은 실측에서 바이트 수까지 동일한 같은 파일이었다. URL 로
    중복을 걷어내면 보통 1개만 남는다 — 그래서 화질 선택 UI 가 뜨지 않는다.
    """
    seen: set[str] = set()
    versions: list[dict[str, Any]] = []
    for version in node.get("video_versions") or []:
        if not isinstance(version, dict):
            continue
        url = str(version.get("url") or "")
        if not url.startswith("http") or url in seen:
            continue
        seen.add(url)
        versions.append(version)
    versions.sort(key=lambda v: v.get("type") or 0)

    return [
        FormatOption(
            id=str(version.get("type") or rank),
            ext="mp4",
            vcodec="h264",
            acodec="aac" if node.get("has_audio", True) else "none",
            note="원본" if rank == 0 else f"화질 {version.get('type')}",
            url=str(version["url"]),
            protocol="https",
        )
        for rank, version in enumerate(versions)
    ]


def _thumbnail(node: dict[str, Any]) -> str | None:
    """썸네일은 작은 것으로 고른다 — 원본 webp 를 그리면 느리다."""
    candidates = ((node.get("image_versions2") or {}).get("candidates")) or []
    sized = [
        c for c in candidates
        if isinstance(c, dict) and isinstance(c.get("url"), str) and c.get("width")
    ]
    if not sized:
        return None
    wide_enough = [c for c in sized if (c.get("width") or 0) >= 320]
    pool = wide_enough or sized
    return str(min(pool, key=lambda c: c.get("width") or 0)["url"])


def _node_to_item(node: dict[str, Any], index: int) -> MediaItem | None:
    is_video = node.get("media_type") == MEDIA_VIDEO or bool(node.get("video_versions"))
    formats = _video_formats(node) if is_video else _image_formats(node)
    if not formats:
        return None

    best = formats[0]
    return MediaItem(
        id=str(index),
        index=index,
        type="video" if is_video else "image",
        title=node.get("accessibility_caption"),
        thumbnail=_thumbnail(node),
        # 실제로 받게 되는 크기만 적는다. 동영상은 비워둔다.
        width=best.width,
        height=best.height,
        formats=formats,
    )


def _taken_at(node: dict[str, Any]) -> datetime | None:
    raw = node.get("taken_at")
    if isinstance(raw, int | float) and raw > 0:
        try:
            return datetime.fromtimestamp(raw)
        except (OSError, OverflowError, ValueError):
            return None
    return None


def to_media_info(parsed: ParsedUrl, node: dict[str, Any], *, used_cookies: bool) -> MediaInfo:
    nodes = node.get("carousel_media")
    if not isinstance(nodes, list) or not nodes:
        nodes = [node]

    items: list[MediaItem] = []
    missing = 0
    for child in nodes:
        item = _node_to_item(child, len(items)) if isinstance(child, dict) else None
        if item is None:
            missing += 1
            continue
        items.append(item)

    if not items:
        # 텍스트 전용 글은 실패가 아니라 "받을 게 없음"이다. 엔진 업데이트를
        # 권하는 ENGINE_FAILED 문구가 나가면 엉뚱한 안내가 된다.
        raise ArchGrabError(ErrorCode.UNSUPPORTED, TEXT_ONLY)

    user = node.get("user") or {}
    username = user.get("username") or parsed.username
    caption = ((node.get("caption") or {}).get("text")) or None

    return MediaInfo(
        platform=parsed.platform,
        kind=parsed.kind,
        source_url=parsed.url,
        key=parsed.key,
        title=caption,
        uploader=username,
        uploader_url=f"https://www.threads.com/@{username}" if username else None,
        description=caption,
        taken_at=_taken_at(node),
        items=items,
        engine=NAME,
        used_cookies=used_cookies,
        missing_items=missing,
    )


def probe(parsed: ParsedUrl, cookies: Path | None = None) -> MediaInfo:
    node = _fetch_node(parsed, cookies)
    return to_media_info(parsed, node, used_cookies=cookies is not None)
