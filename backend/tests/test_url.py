from __future__ import annotations

import pytest

from app.core.errors import ErrorCode, ArchGrabError
from app.core.url import Kind, Platform, parse_url


@pytest.mark.parametrize(
    ("raw", "platform", "kind", "key"),
    [
        # 인스타그램
        ("https://www.instagram.com/p/CxYzAbC123/", Platform.INSTAGRAM, Kind.POST, "CxYzAbC123"),
        ("instagram.com/p/CxYzAbC123", Platform.INSTAGRAM, Kind.POST, "CxYzAbC123"),
        ("https://www.instagram.com/reel/DAbc_9-xyz/", Platform.INSTAGRAM, Kind.REEL, "DAbc_9-xyz"),
        ("https://www.instagram.com/reels/DAbc_9-xyz/", Platform.INSTAGRAM, Kind.REEL, "DAbc_9-xyz"),
        ("https://www.instagram.com/tv/DAbc_9-xyz/", Platform.INSTAGRAM, Kind.REEL, "DAbc_9-xyz"),
        ("https://www.instagram.com/someuser/p/CxYzAbC123/", Platform.INSTAGRAM, Kind.POST, "CxYzAbC123"),
        ("https://www.instagram.com/stories/someuser/3412345678901234567/",
         Platform.INSTAGRAM, Kind.STORY, "3412345678901234567"),
        ("https://www.instagram.com/stories/highlights/17899999999999999/",
         Platform.INSTAGRAM, Kind.HIGHLIGHT, "17899999999999999"),
        ("https://www.instagram.com/someuser/", Platform.INSTAGRAM, Kind.PROFILE, "someuser"),
        # X
        ("https://x.com/someone/status/1838000000000000000", Platform.X, Kind.TWEET, "1838000000000000000"),
        ("https://twitter.com/someone/status/1838000000000000000", Platform.X, Kind.TWEET, "1838000000000000000"),
        ("https://x.com/someone/status/1838000000000000000/photo/2", Platform.X, Kind.TWEET, "1838000000000000000"),
        ("https://x.com/i/web/status/1838000000000000000", Platform.X, Kind.TWEET, "1838000000000000000"),
        # 유튜브
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=30s", Platform.YOUTUBE, Kind.VIDEO, "dQw4w9WgXcQ"),
        ("https://youtu.be/dQw4w9WgXcQ?si=abc", Platform.YOUTUBE, Kind.VIDEO, "dQw4w9WgXcQ"),
        ("https://www.youtube.com/shorts/dQw4w9WgXcQ", Platform.YOUTUBE, Kind.SHORTS, "dQw4w9WgXcQ"),
        ("https://m.youtube.com/watch?v=dQw4w9WgXcQ", Platform.YOUTUBE, Kind.VIDEO, "dQw4w9WgXcQ"),
    ],
)
def test_parse_supported(raw: str, platform: Platform, kind: Kind, key: str) -> None:
    parsed = parse_url(raw)
    assert (parsed.platform, parsed.kind, parsed.key) == (platform, kind, key)


def test_tracking_params_are_dropped() -> None:
    assert parse_url("https://www.instagram.com/p/CxYzAbC123/?igsh=xyz123").url == (
        "https://www.instagram.com/p/CxYzAbC123/"
    )


def test_share_link_needs_redirect() -> None:
    parsed = parse_url("https://www.instagram.com/share/reel/BAbcdEfg/")
    assert parsed.kind is Kind.SHARE and parsed.needs_redirect


def test_username_is_kept_for_stories() -> None:
    parsed = parse_url("https://www.instagram.com/stories/someuser/3412345678901234567/")
    assert parsed.username == "someuser"


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "not a url",
        "https://example.com/p/abc",
        "https://www.instagram.com/explore/",          # 예약 경로는 프로필이 아니다
        "https://www.instagram.com/p/",                # 숏코드 없음
        "https://x.com/someone",                       # 트윗이 아니라 프로필
        "https://x.com/someone/status/abc",            # 숫자 아님
        "https://www.youtube.com/watch?v=tooshort",    # 11자 아님
        "ftp://www.instagram.com/p/CxYzAbC123/",
    ],
)
def test_parse_unsupported(raw: str) -> None:
    with pytest.raises(ArchGrabError) as caught:
        parse_url(raw)
    assert caught.value.code is ErrorCode.UNSUPPORTED
