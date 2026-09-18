"""인스타그램 비로그인 웹 API 클라이언트.

yt-dlp 가 쓰는 것과 **같은** 익명 GraphQL 엔드포인트를 직접 호출한다. yt-dlp 를
그대로 쓰지 않는 이유는 하나다: yt-dlp 는 이미지 항목을 버린다("No video formats
found!"). 15장 캐러셀에서 동영상 3개만 남고 이미지 12개가 조용히 사라진다.
같은 응답에 이미지 정보가 전부 들어 있으므로 우리가 직접 읽는다.

전제 조건은 **브라우저 TLS 지문 위장**(curl_cffi)이다. 위장 없이는 로그인
페이지로 리다이렉트된다. 로그인은 필요 없다.

응답에서 확인한 구조:
  if_not_gated_logged_out
    ├─ media_type      1=이미지 2=동영상 8=캐러셀
    ├─ caption.text / user.username / code / taken_at
    ├─ original_width, original_height        ← 업로드 원본 해상도
    ├─ image_versions2.candidates[]           ← url 만 있고 크기는 없음.
    │                                            stp 파라미터가 서빙 크기를 정한다.
    │                                            크기 토큰이 없는 후보가 원본이다.
    ├─ video_versions[]                       ← progressive mp4 (영상+음성). type 낮을수록 고화질
    └─ carousel_media[]                       ← 항목별로 위 구조 반복
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

NAME = "instagram-web"

APP_ID = "936619743392459"
DOC_ID = "27130156389949648"
FRIENDLY_NAME = "PolarisLoggedOutDesktopWWWPostRootContentQuery"
GRAPHQL_URL = "https://www.instagram.com/api/graphql"
RULING_URL = "https://www.instagram.com/api/v1/web/get_ruling_for_content/"

MEDIA_IMAGE = 1
MEDIA_VIDEO = 2
MEDIA_CAROUSEL = 8

_LSD_PATTERNS = (
    re.compile(r'"LSD",\[\],\{"token":"([^"]+)"'),
    re.compile(r'"lsd":"([^"]+)"'),
)
# stp 안의 크기 토큰. 예: p1080x1080, s640x640
_SIZE_TOKEN = re.compile(r"[ps](\d+)x(\d+)")


def is_available() -> bool:
    """curl_cffi 가 있는지. 없으면 이 경로 자체가 성립하지 않는다."""
    try:
        import curl_cffi  # noqa: F401
    except ImportError:
        return False
    return True


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


def _shortcode_to_media_id(shortcode: str) -> str:
    # yt-dlp 가 이미 검증해둔 변환을 재사용한다 (숏코드는 커스텀 base64 다)
    from yt_dlp.extractor.instagram import _id_to_pk

    return str(_id_to_pk(shortcode))


def _fail(code: ErrorCode, detail: str | None = None) -> ArchGrabError:
    return ArchGrabError(code, detail=mask_secrets(detail) if detail else None)


def _fetch_payload(parsed: ParsedUrl, cookies: Path | None) -> dict[str, Any]:
    if not is_available():
        raise ArchGrabError(
            ErrorCode.ENGINE_FAILED,
            "curl_cffi 가 설치되지 않아 비로그인 접근을 쓸 수 없습니다. `make install` 을 실행해주세요.",
        )

    from curl_cffi import requests as curl_requests

    session = _session(cookies)
    try:
        page = session.get(parsed.url)
        if "accounts/login" in str(getattr(page, "url", "")):
            raise _fail(ErrorCode.LOGIN_REQUIRED, "게시글 페이지가 로그인으로 리다이렉트됨")
        if page.status_code == 404:
            raise _fail(ErrorCode.NOT_FOUND)
        if page.status_code >= 400:
            raise _fail(ErrorCode.ENGINE_FAILED, f"게시글 페이지 HTTP {page.status_code}")

        lsd = next(
            (m.group(1) for pattern in _LSD_PATTERNS if (m := pattern.search(page.text))), None
        )
        if not lsd:
            raise _fail(ErrorCode.ENGINE_FAILED, "LSD 토큰을 찾지 못함 (페이지 구조 변경 가능)")

        media_id = _shortcode_to_media_id(parsed.key)

        # csrftoken 쿠키를 받기 위한 호출. 실패해도 계속 시도한다.
        session.get(
            RULING_URL,
            params={"content_type": "MEDIA", "target_id": media_id},
            headers={"X-IG-App-ID": APP_ID},
        )

        response = session.post(
            GRAPHQL_URL,
            headers={
                "X-IG-App-ID": APP_ID,
                "X-CSRFToken": session.cookies.get("csrftoken") or "",
                "X-FB-LSD": lsd,
                "X-Requested-With": "XMLHttpRequest",
                "X-FB-Friendly-Name": FRIENDLY_NAME,
                "Referer": parsed.url,
            },
            data={
                "lsd": lsd,
                "fb_api_caller_class": "RelayModern",
                "fb_api_req_friendly_name": FRIENDLY_NAME,
                "server_timestamps": "true",
                "variables": json.dumps({"media_id": media_id}, separators=(",", ":")),
                "doc_id": DOC_ID,
            },
        )
    except ArchGrabError:
        raise
    except curl_requests.errors.RequestsError as exc:
        raise _fail(ErrorCode.TIMEOUT, str(exc)) from exc
    except Exception as exc:  # curl_cffi 는 다양한 예외를 올린다
        raise _fail(ErrorCode.ENGINE_FAILED, str(exc)) from exc
    finally:
        session.close()

    if response.status_code >= 400:
        raise _fail(ErrorCode.ENGINE_FAILED, f"GraphQL HTTP {response.status_code}")

    try:
        body = response.json()
    except (ValueError, json.JSONDecodeError) as exc:
        raise _fail(ErrorCode.ENGINE_FAILED, "GraphQL 응답이 JSON 이 아님") from exc

    media = (body.get("data") or {}).get("xig_polaris_media") or {}
    payload = media.get("if_not_gated_logged_out")
    if not isinstance(payload, dict) or not payload:
        # 비공개·삭제·연령제한이면 게이팅되어 빈 응답이 온다
        raise ArchGrabError(
            ErrorCode.LOGIN_REQUIRED,
            "비로그인으로는 볼 수 없는 게시글입니다 (비공개·삭제·제한). "
            "쿠키를 등록하면 접근할 수 있습니다.",
        )
    return payload


# ---- 정규화 --------------------------------------------------------------

def _pick_original_image(candidates: list[dict[str, Any]]) -> str | None:
    """크기 토큰이 없는 후보가 원본이다.

    후보에는 url 만 있고 width/height 가 없다. 대신 stp 파라미터가 서빙 크기를
    정한다 — `dst-jpegr_e35_tt6` 처럼 크기 토큰이 없으면 원본 그대로 내려온다.
    실측으로 확인했다(3072x4096, 보고된 original_width/height 와 일치).
    """
    best_url: str | None = None
    best_pixels = -1

    for candidate in candidates:
        url = candidate.get("url")
        if not isinstance(url, str) or not url.startswith("http"):
            continue
        stp = (parse_qs(urlparse(url).query).get("stp") or [""])[0]
        match = _SIZE_TOKEN.search(stp)
        # 크기 토큰이 없으면 무제한 = 원본
        pixels = int(match.group(1)) * int(match.group(2)) if match else 1 << 40
        if pixels > best_pixels:
            best_pixels, best_url = pixels, url

    return best_url


def _image_formats(node: dict[str, Any]) -> list[FormatOption]:
    candidates = ((node.get("image_versions2") or {}).get("candidates")) or []
    url = _pick_original_image(candidates) or node.get("display_uri")
    if not isinstance(url, str):
        return []
    ext = "jpg"
    path = urlparse(url).path.rsplit(".", 1)
    if len(path) == 2 and len(path[-1]) <= 5:
        ext = path[-1].lower()
    return [
        FormatOption(
            id="original",
            ext=ext,
            width=node.get("original_width"),
            height=node.get("original_height"),
            note="원본",
            url=url,
            protocol="https",
        )
    ]


def _video_formats(node: dict[str, Any]) -> list[FormatOption]:
    """video_versions 는 progressive mp4 다 (mux 불필요).

    **해상도를 주장하지 않는다.** 노드의 original_width/height 는 업로더가 올린
    원본 크기이고, 실제로 서빙되는 렌디션은 그보다 작다 — 실측에서 노드가
    1080x1440 이라 보고한 항목의 실제 파일은 720x960 이었다. 그걸 화면에
    표시하면 "보이는 것"과 "받는 것"이 어긋난다.

    type 은 낮을수록 고화질이라 오름차순으로 둔다. 같은 URL 이 여러 type 으로
    중복되는 경우가 흔해서(실측: 3개 모두 바이트까지 동일) URL 기준으로 합친다.
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
            # 원본에 음성 트랙이 없는 클립도 흔하다 (has_audio=False)
            acodec="aac" if node.get("has_audio") else "none",
            note="원본" if rank == 0 else f"화질 {version.get('type')}",
            url=version["url"],
            protocol="https",
        )
        for rank, version in enumerate(versions)
    ]


def _node_to_item(node: dict[str, Any], index: int) -> MediaItem | None:
    media_type = node.get("media_type")
    is_video = media_type == MEDIA_VIDEO
    formats = _video_formats(node) if is_video else _image_formats(node)
    if not formats:
        return None

    best = formats[0]
    return MediaItem(
        id=str(index),
        index=index,
        type="video" if is_video else "image",
        title=node.get("accessibility_caption"),
        thumbnail=node.get("display_uri"),
        # 실제로 받게 되는 크기만 적는다. 동영상은 렌디션 크기를 알 수 없어 비워둔다
        # (노드의 original_* 는 업로드 원본이라 서빙 크기와 다르다).
        width=best.width,
        height=best.height,
        formats=formats,
    )


def _taken_at(payload: dict[str, Any]) -> datetime | None:
    raw = payload.get("taken_at")
    if isinstance(raw, int | float) and raw > 0:
        try:
            return datetime.fromtimestamp(raw)
        except (OSError, OverflowError, ValueError):
            return None
    return None


def to_media_info(parsed: ParsedUrl, payload: dict[str, Any], *, used_cookies: bool) -> MediaInfo:
    nodes = payload.get("carousel_media")
    if not isinstance(nodes, list) or not nodes:
        nodes = [payload]

    items: list[MediaItem] = []
    missing = 0
    for node in nodes:
        item = _node_to_item(node, len(items)) if isinstance(node, dict) else None
        if item is None:
            missing += 1
            continue
        items.append(item)

    if not items:
        raise ArchGrabError(ErrorCode.ENGINE_FAILED, "내려받을 미디어를 찾지 못했습니다.")

    user = payload.get("user") or {}
    username = user.get("username")
    caption = ((payload.get("caption") or {}).get("text")) or None

    return MediaInfo(
        platform=parsed.platform,
        kind=parsed.kind,
        source_url=parsed.url,
        key=parsed.key,
        title=caption,
        uploader=username or parsed.username,
        uploader_url=f"https://www.instagram.com/{username}/" if username else None,
        description=caption,
        taken_at=_taken_at(payload),
        items=items,
        engine=NAME,
        used_cookies=used_cookies,
        missing_items=missing,
    )


def probe(parsed: ParsedUrl, cookies: Path | None = None) -> MediaInfo:
    payload = _fetch_payload(parsed, cookies)
    return to_media_info(parsed, payload, used_cookies=cookies is not None)
