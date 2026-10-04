"""URL → (플랫폼, 종류, 키) 판별.

네트워크를 타지 않는 순수 파싱 계층. 여기서 걸러진 주소만 추출 엔진으로 넘어간다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import parse_qs, urlparse

from app.core.errors import ErrorCode, ArchGrabError


class Platform(StrEnum):
    INSTAGRAM = "instagram"
    THREADS = "threads"
    X = "x"
    YOUTUBE = "youtube"


class Kind(StrEnum):
    POST = "post"            # 인스타 /p/ — 이미지·동영상·캐러셀 어느 쪽인지는 해석 후 확정
    REEL = "reel"            # 인스타 /reel/ /reels/ /tv/
    STORY = "story"
    HIGHLIGHT = "highlight"
    PROFILE = "profile"
    SHARE = "share"          # 인스타 /share/ — 실제 주소로 리다이렉트 추적 필요
    TWEET = "tweet"
    VIDEO = "video"
    SHORTS = "shorts"
    PLAYLIST = "playlist"


@dataclass(frozen=True, slots=True)
class ParsedUrl:
    platform: Platform
    kind: Kind
    key: str
    url: str                      # 추적 파라미터를 제거한 정규화 주소
    username: str | None = None
    needs_redirect: bool = False  # 실제 대상을 알기 위해 HTTP 추적이 필요한 경우

    @property
    def cache_key(self) -> str:
        return f"{self.platform}:{self.kind}:{self.username or '-'}:{self.key}"


INSTAGRAM_HOSTS = frozenset({"instagram.com", "instagr.am", "ig.me"})
# threads.net 은 threads.com 으로 리다이렉트된다 (확인함). 둘 다 받는다.
THREADS_HOSTS = frozenset({"threads.com", "threads.net"})
X_HOSTS = frozenset({"x.com", "twitter.com", "t.co", "vxtwitter.com", "fixupx.com"})
YOUTUBE_HOSTS = frozenset({"youtube.com", "youtu.be", "youtube-nocookie.com"})

# 프로필로 오인하면 안 되는 인스타 예약 경로
_IG_RESERVED = frozenset({
    "explore", "accounts", "direct", "reels", "stories", "p", "tv", "reel",
    "about", "legal", "developer", "api", "web", "challenge", "emails",
    "session", "graphql", "ajax", "oauth", "privacy", "terms", "your_activity",
})
_IG_MEDIA_SEGMENTS = frozenset({"p", "reel", "reels", "tv"})
_IG_SHORTCODE = re.compile(r"^[A-Za-z0-9_-]{5,32}$")
_DIGITS = re.compile(r"^\d{5,25}$")
_YT_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


def _base_host(netloc: str) -> str:
    host = netloc.split("@")[-1].split(":")[0].lower()
    host = host.removeprefix("www.").removeprefix("m.").removeprefix("mobile.")
    host = host.removeprefix("music.")
    return host


def _segments(path: str) -> list[str]:
    return [s for s in path.split("/") if s]


def _unsupported(raw: str) -> ArchGrabError:
    return ArchGrabError(ErrorCode.UNSUPPORTED, detail=raw[:200])


def parse_url(raw: str) -> ParsedUrl:
    """지원 주소면 ParsedUrl, 아니면 ArchGrabError(UNSUPPORTED)."""
    text = (raw or "").strip()
    if not text:
        raise _unsupported(raw)
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", text):
        text = "https://" + text

    parts = urlparse(text)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise _unsupported(raw)

    host = _base_host(parts.netloc)
    segs = _segments(parts.path)
    query = parse_qs(parts.query)

    if host in INSTAGRAM_HOSTS:
        return _parse_instagram(raw, host, segs)
    if host in THREADS_HOSTS:
        return _parse_threads(raw, segs)
    if host in X_HOSTS:
        return _parse_x(raw, host, segs)
    if host in YOUTUBE_HOSTS:
        return _parse_youtube(raw, host, segs, query)
    raise _unsupported(raw)


def _parse_instagram(raw: str, host: str, segs: list[str]) -> ParsedUrl:
    if host in {"instagr.am", "ig.me"} or not segs:
        if not segs:
            raise _unsupported(raw)

    head = segs[0].lower()

    # /share/... , /share/reel/... — 대상을 모르므로 리다이렉트 추적으로 넘긴다
    if head == "share":
        if len(segs) < 2:
            raise _unsupported(raw)
        return ParsedUrl(
            Platform.INSTAGRAM, Kind.SHARE, segs[-1],
            f"https://www.instagram.com/{'/'.join(segs)}/", needs_redirect=True,
        )

    # /stories/{user}/{id} , /stories/highlights/{id}
    if head == "stories":
        if len(segs) >= 3 and segs[1].lower() == "highlights":
            return ParsedUrl(
                Platform.INSTAGRAM, Kind.HIGHLIGHT, segs[2],
                f"https://www.instagram.com/stories/highlights/{segs[2]}/",
            )
        if len(segs) >= 3:
            return ParsedUrl(
                Platform.INSTAGRAM, Kind.STORY, segs[2],
                f"https://www.instagram.com/stories/{segs[1]}/{segs[2]}/", username=segs[1],
            )
        if len(segs) == 2:
            # 사용자 스토리 전체
            return ParsedUrl(
                Platform.INSTAGRAM, Kind.STORY, "",
                f"https://www.instagram.com/stories/{segs[1]}/", username=segs[1],
            )
        raise _unsupported(raw)

    # /p/{code} , /reel/{code} , /reels/{code} , /tv/{code}
    if head in _IG_MEDIA_SEGMENTS and len(segs) >= 2:
        return _instagram_media(raw, head, segs[1], username=None)

    # /{username}/p/{code} 형태도 유효한 주소다
    if len(segs) >= 3 and segs[1].lower() in _IG_MEDIA_SEGMENTS:
        return _instagram_media(raw, segs[1].lower(), segs[2], username=segs[0])

    # /{username}
    if len(segs) == 1 and head not in _IG_RESERVED and _IG_SHORTCODE.match(segs[0]):
        return ParsedUrl(
            Platform.INSTAGRAM, Kind.PROFILE, segs[0],
            f"https://www.instagram.com/{segs[0]}/", username=segs[0],
        )

    raise _unsupported(raw)


def _instagram_media(raw: str, segment: str, code: str, *, username: str | None) -> ParsedUrl:
    if not _IG_SHORTCODE.match(code):
        raise _unsupported(raw)
    kind = Kind.POST if segment == "p" else Kind.REEL
    path = "p" if segment == "p" else ("tv" if segment == "tv" else "reel")
    return ParsedUrl(
        Platform.INSTAGRAM, kind, code,
        f"https://www.instagram.com/{path}/{code}/", username=username,
    )


# 스레드 사용자명. 인스타 숏코드 패턴(최소 5자)을 재사용하면 네 글자 계정
# (@zuck)이 걸러진다.
_THREADS_USERNAME = re.compile(r"^[A-Za-z0-9._]{1,30}$")


def _parse_threads(raw: str, segs: list[str]) -> ParsedUrl:
    """스레드 주소 4가지 형태를 모두 받는다 (전부 실제 응답으로 확인함).

    `/@{user}/post/{code}` · `/{user}/post/{code}` · `/t/{code}` · `/@{user}`

    주소의 사용자명은 **장식이다**. 남의 사용자명을 붙여도 같은 게시글이
    내려온다(확인함). 권위 있는 건 code 뿐이라 key 로 쓰고, 엔진은 사용자명이
    필요 없는 `/t/{code}` 로 요청한다.
    """
    if not segs:
        raise _unsupported(raw)

    head = segs[0]
    lowered = [s.lower() for s in segs]

    # /share/{토큰} — 모바일 앱의 공유 버튼이 주는 형태다. 토큰은 숏코드가
    # 아니라 별개 식별자라(실측: 9자 토큰 → 11자 숏코드) 추적해야 알 수 있다.
    # 추적 없이 엔진에 넘기면 엉뚱한 글을 찾다가 "찾을 수 없습니다"가 나간다.
    if lowered[0] == "share" and len(segs) >= 2:
        return ParsedUrl(
            Platform.THREADS, Kind.SHARE, segs[-1],
            f"https://www.threads.com/{'/'.join(segs)}/", needs_redirect=True,
        )

    # /t/{code} — 사용자명 없이도 서버가 대상을 해결해준다
    if lowered[0] == "t" and len(segs) >= 2:
        return _threads_post(raw, segs[1], username=None)

    # /@{user}/post/{code} , /{user}/post/{code}
    if len(segs) >= 3 and lowered[1] == "post":
        return _threads_post(raw, segs[2], username=head.removeprefix("@") or None)

    # /@{user} — @ 가 붙은 형태만 프로필로 본다. @ 없는 한 조각짜리 주소를
    # 사용자명으로 받으면 /search 같은 예약 경로까지 끌어안게 된다. @ 가 붙으면
    # 예약 경로와 겹칠 수 없으므로 @t · @about 같은 실제 계정도 그대로 통과한다.
    if len(segs) == 1 and head.startswith("@"):
        user = head.removeprefix("@")
        if _THREADS_USERNAME.match(user):
            return ParsedUrl(
                Platform.THREADS, Kind.PROFILE, user,
                f"https://www.threads.com/@{user}", username=user,
            )

    raise _unsupported(raw)


def _threads_post(raw: str, code: str, *, username: str | None) -> ParsedUrl:
    if not _IG_SHORTCODE.match(code):
        raise _unsupported(raw)
    url = (
        f"https://www.threads.com/@{username}/post/{code}"
        if username
        else f"https://www.threads.com/t/{code}"
    )
    return ParsedUrl(Platform.THREADS, Kind.POST, code, url, username=username)


def _parse_x(raw: str, host: str, segs: list[str]) -> ParsedUrl:
    if host == "t.co":
        # 단축 링크는 대상을 알 수 없다
        if not segs:
            raise _unsupported(raw)
        return ParsedUrl(Platform.X, Kind.TWEET, segs[0], f"https://t.co/{segs[0]}",
                         needs_redirect=True)

    lowered = [s.lower() for s in segs]
    if "status" in lowered:
        i = lowered.index("status")
        if len(segs) <= i + 1 or not _DIGITS.match(segs[i + 1]):
            raise _unsupported(raw)
        tweet_id = segs[i + 1]
        username = segs[0] if i > 0 and lowered[0] not in {"i", "web"} else None
        return ParsedUrl(
            Platform.X, Kind.TWEET, tweet_id,
            f"https://x.com/{username or 'i'}/status/{tweet_id}", username=username,
        )
    raise _unsupported(raw)


def _parse_youtube(
    raw: str, host: str, segs: list[str], query: dict[str, list[str]]
) -> ParsedUrl:
    if host == "youtu.be":
        if segs and _YT_ID.match(segs[0]):
            return _yt_video(segs[0], Kind.VIDEO)
        raise _unsupported(raw)

    head = segs[0].lower() if segs else ""

    if head == "watch":
        vid = (query.get("v") or [""])[0]
        if _YT_ID.match(vid):
            return _yt_video(vid, Kind.VIDEO)
        raise _unsupported(raw)

    if head in {"shorts", "live", "embed", "v"} and len(segs) >= 2:
        if not _YT_ID.match(segs[1]):
            raise _unsupported(raw)
        return _yt_video(segs[1], Kind.SHORTS if head == "shorts" else Kind.VIDEO)

    if head == "playlist":
        plist = (query.get("list") or [""])[0]
        if plist:
            return ParsedUrl(
                Platform.YOUTUBE, Kind.PLAYLIST, plist,
                f"https://www.youtube.com/playlist?list={plist}",
            )
        raise _unsupported(raw)

    raise _unsupported(raw)


def _yt_video(vid: str, kind: Kind) -> ParsedUrl:
    return ParsedUrl(Platform.YOUTUBE, kind, vid, f"https://www.youtube.com/watch?v={vid}")
