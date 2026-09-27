"""공유 링크 추적.

추적하지 않으면 공유 코드를 숏코드로 착각해 엉뚱한 media_id 가 만들어지고,
공개 게시글인데도 "비공개·삭제·제한" 이라는 틀린 안내가 나갔다. 모바일 공유
버튼이 주는 형태라 실사용에서 가장 먼저 부딪치는 경로다.
"""

from __future__ import annotations

import pytest

from app.core.errors import ArchGrabError, ErrorCode
from app.core.link import follow
from app.core.url import Kind, Platform, parse_url

SHARE = "https://www.instagram.com/share/BAbcdEfgHi/"
POST = "https://www.instagram.com/p/DdG0csnmPlQ/"


def fetcher(url: str, body: str = ""):  # noqa: ANN201
    return lambda _: (url, body)


def test_normal_url_is_untouched() -> None:
    """추적이 필요 없는 주소는 네트워크를 타지 않는다."""
    parsed = parse_url(POST)

    def explode(_: str):  # noqa: ANN202
        raise AssertionError("호출되면 안 된다")

    assert follow(parsed, explode) is parsed


def test_share_link_resolves_to_the_post() -> None:
    resolved = follow(parse_url(SHARE), fetcher(POST))
    assert (resolved.kind, resolved.key) == (Kind.POST, "DdG0csnmPlQ")
    assert not resolved.needs_redirect


def test_share_link_resolves_to_a_reel() -> None:
    resolved = follow(parse_url(SHARE), fetcher("https://www.instagram.com/reel/CDUMkliABpa/"))
    assert (resolved.kind, resolved.key) == (Kind.REEL, "CDUMkliABpa")


def test_canonical_in_body_is_used_when_no_redirect_happens() -> None:
    """JS 로 그리는 껍데기만 오고 리다이렉트가 없는 경우."""
    body = f'<html><head><link rel="canonical" href="{POST}"/></head></html>'
    resolved = follow(parse_url(SHARE), fetcher(SHARE, body))
    assert resolved.key == "DdG0csnmPlQ"


def test_og_url_is_used_as_a_fallback() -> None:
    body = f'<html><head><meta property="og:url" content="{POST}"></head></html>'
    resolved = follow(parse_url(SHARE), fetcher(SHARE, body))
    assert resolved.key == "DdG0csnmPlQ"


def test_login_redirect_says_login_required() -> None:
    with pytest.raises(ArchGrabError) as caught:
        follow(parse_url(SHARE), fetcher("https://www.instagram.com/accounts/login/?next=/p/X/"))
    assert caught.value.code is ErrorCode.LOGIN_REQUIRED


def test_unresolvable_share_link_is_not_passed_to_the_engine() -> None:
    """가장 중요한 케이스 — 추적 실패를 조용히 넘기면 '비공개' 라는 거짓 안내가 나간다."""
    with pytest.raises(ArchGrabError) as caught:
        follow(parse_url(SHARE), fetcher(SHARE, "<html>no canonical</html>"))
    assert caught.value.code is ErrorCode.UNSUPPORTED
    assert "게시글 주소를 직접" in caught.value.message


def test_network_failure_gives_an_actionable_message() -> None:
    def boom(_: str):  # noqa: ANN202
        raise OSError("connection reset")

    with pytest.raises(ArchGrabError) as caught:
        follow(parse_url(SHARE), boom)
    assert caught.value.code is ErrorCode.ENGINE_FAILED
    assert "게시글 링크를 직접" in caught.value.message


def test_x_short_link_is_followed_too() -> None:
    parsed = parse_url("https://t.co/AbCdEf")
    assert parsed.platform is Platform.X and parsed.needs_redirect
    resolved = follow(parsed, fetcher("https://x.com/someone/status/1838000000000000000"))
    assert (resolved.kind, resolved.key) == (Kind.TWEET, "1838000000000000000")


@pytest.mark.network
def test_real_instagram_redirect_is_followed() -> None:
    """전송 계층 확인 — 위장 없이는 인스타가 로그인으로 돌려보낸다."""
    from app.core.link import _default_fetch

    final, _ = _default_fetch("http://instagram.com/p/DdG0csnmPlQ")
    assert "/p/DdG0csnmPlQ" in final
    assert "accounts/login" not in final
