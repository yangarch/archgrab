"""파싱은 되지만 처리기가 없는 종류 — 거절 문구가 사실과 맞아야 한다.

주소 모양만 보는 파서는 프로필·재생목록도 통과시킨다. 그대로 엔진에 넘기면
엉뚱한 실패가 나고 그 문구가 오류 분류기에서 **틀린 원인**으로 접힌다. 실제로
두 건이 그렇게 나가고 있었다:

- 인스타 프로필 → "비공개·삭제·제한… 쿠키를 등록하면 접근할 수 있습니다"
  (쿠키를 등록해도 안 되는데 사용자를 등록하러 보냈다)
- 유튜브 재생목록 → "삭제되었거나 존재하지 않는 콘텐츠입니다"
  (실제로 존재하는 재생목록으로 확인했다)

그래서 거절은 엔진 **앞**에 둔다. 이 테스트들은 네트워크를 타지 않는다 —
타기 시작하면 가드가 사라진 것이다.
"""

from __future__ import annotations

import pytest

from app.core.errors import ArchGrabError, ErrorCode
from app.core.url import Kind, Platform, parse_url
from app.extractors import instagram, threads, youtube
from app.extractors.base import Selection
from app.extractors.registry import get_extractor

# (플랫폼 모듈, 거절되어야 하는 주소)
CASES = [
    (instagram, "https://www.instagram.com/natgeo/", Kind.PROFILE),
    (threads, "https://www.threads.com/@zuck", Kind.PROFILE),
    (youtube, "https://www.youtube.com/playlist?list=UUfDfvvMARk4TKcC62ALi6eA", Kind.PLAYLIST),
]

# 과거에 실제로 나갔던 틀린 방향. 이 단어가 다시 들어가면 같은 오진이다.
MISLEADING = ("쿠키", "업데이트", "삭제", "비공개")


@pytest.mark.parametrize(("module", "url", "kind"), CASES)
def test_probe_rejects_before_touching_the_engine(module, url: str, kind: Kind) -> None:
    parsed = parse_url(url)
    assert parsed.kind is kind          # 파서는 여전히 통과시킨다 (여기서 막는 게 아니다)

    with pytest.raises(ArchGrabError) as exc:
        get_extractor(parsed.platform).probe(parsed)

    assert exc.value.code is ErrorCode.UNSUPPORTED
    assert exc.value.message == module.UNSUPPORTED_KINDS[kind]


@pytest.mark.parametrize(("module", "url", "kind"), CASES)
def test_download_rejects_too(module, url: str, kind: Kind, tmp_path) -> None:
    """probe 만 막으면 작업 큐로 들어온 같은 주소가 엔진을 때린다."""
    parsed = parse_url(url)
    with pytest.raises(ArchGrabError) as exc:
        get_extractor(parsed.platform).download(parsed, Selection(), tmp_path)
    assert exc.value.code is ErrorCode.UNSUPPORTED


@pytest.mark.parametrize(("module", "url", "kind"), CASES)
def test_message_does_not_blame_cookies_or_a_stale_engine(module, url: str, kind: Kind) -> None:
    """무엇을 해야 하는지 알려주되, 해도 안 되는 일을 권하지 않는다."""
    message = module.UNSUPPORTED_KINDS[kind]
    for word in MISLEADING:
        assert word not in message, f"{word!r} 가 다시 들어갔다: {message!r}"
    # 대안을 제시해야 한다 — 막기만 하면 사용자가 다음에 뭘 할지 모른다
    assert "주소를 넣어주세요" in message


def test_story_still_points_at_cookies() -> None:
    """스토리는 쿠키로 **실제로** 해결된다 — 이건 틀린 안내가 아니다.

    "틀린 안내 제거"를 과하게 적용해 이쪽까지 UNSUPPORTED 로 바꾸면,
    해결 방법이 있는데 없다고 말하는 반대 방향의 오진이 된다.
    """
    parsed = parse_url("https://www.instagram.com/stories/natgeo/3500000000000000000/")
    with pytest.raises(ArchGrabError) as exc:
        instagram.extractor.probe(parsed)
    assert exc.value.code is ErrorCode.LOGIN_REQUIRED
    assert "쿠키" in exc.value.message


def test_x_has_nothing_to_declare() -> None:
    """X 파서는 TWEET 하나만 만든다 — 선언할 미지원 종류가 없다.

    이 테스트는 X 파서가 나중에 프로필·목록을 받기 시작하면 깨진다. 그때
    UNSUPPORTED_KINDS 를 같이 두라는 신호다.
    """
    from app.extractors import x

    assert not getattr(x, "UNSUPPORTED_KINDS", {})
    for raw in ("https://x.com/natgeo", "https://x.com/i/lists/1234567890"):
        with pytest.raises(ArchGrabError) as exc:
            parse_url(raw)
        assert exc.value.code is ErrorCode.UNSUPPORTED


def test_every_declared_kind_is_actually_producible_by_the_parser() -> None:
    """선언이 현실과 맞는지. 못 만드는 종류를 막아두면 죽은 코드가 쌓인다."""
    producible = {
        Platform.INSTAGRAM: {Kind.POST, Kind.REEL, Kind.STORY, Kind.HIGHLIGHT,
                             Kind.PROFILE, Kind.SHARE},
        Platform.THREADS: {Kind.POST, Kind.PROFILE, Kind.SHARE},
        Platform.YOUTUBE: {Kind.VIDEO, Kind.SHORTS, Kind.PLAYLIST},
    }
    declared = {
        Platform.INSTAGRAM: instagram.UNSUPPORTED_KINDS,
        Platform.THREADS: threads.UNSUPPORTED_KINDS,
        Platform.YOUTUBE: youtube.UNSUPPORTED_KINDS,
    }
    for platform, kinds in declared.items():
        assert set(kinds) <= producible[platform], platform
