"""스레드 추출 — 실측으로 확인한 함정들을 고정한다.

픽스처는 실제 게시글 응답에서 관찰한 구조를 그대로 옮긴 것이다(필드 이름·중첩·
stp 토큰 형태). 실제 HTML 은 850KB 라 테스트에 넣을 수 없으므로 같은 모양의
최소 문서를 만들어 쓴다.
"""

from __future__ import annotations

import json

import pytest

from app.core.errors import ArchGrabError, ErrorCode
from app.core.url import Kind, Platform, parse_url
from app.extractors import threads, threads_web

CODE = "Ddt7cL5EfUG"
BASE = "https://scontent.cdninstagram.com/v/t51.75761-15"


def _img(width: int, height: int, stp: str | None, name: str = "a.webp") -> dict:
    query = f"?stp={stp}&_nc_cat=1" if stp else "?_nc_cat=1"
    return {"url": f"{BASE}/{name}{query}", "width": width, "height": height}


def _image_node(code: str, *, width: int = 2160, height: int = 2700) -> dict:
    """실측 그대로: 크기 토큰 없는 후보 1개 + 크롭·축소 후보 여럿."""
    return {
        "code": code,
        "media_type": 1,
        "original_width": width,
        "original_height": height,
        "image_versions2": {
            "candidates": [
                # 크롭이 면적상 가장 클 수도 있다 — 면적만 보고 고르면 잘린 걸 집는다
                _img(2160, 2160, "c0.270.2160.2160a_dst-webp_s2160x2160"),
                _img(1080, 1350, "dst-webp_p1080x1080"),
                _img(width, height, None, name="original.webp"),
                _img(640, 800, "dst-webp_p640x640"),
            ]
        },
    }


def _video_node(code: str) -> dict:
    """동영상 노드. image_versions2 는 썸네일뿐이고 크기를 주지 않는다."""
    return {
        "code": code,
        "media_type": 2,
        "original_width": 1080,
        "original_height": 1350,
        "has_audio": True,
        "image_versions2": {"candidates": [_img(640, 800, None, name="thumb.jpg")]},
        # 실측: 세 type 이 바이트까지 같은 파일이었다
        "video_versions": [
            {"type": 101, "url": f"{BASE}/clip.mp4?_nc_cat=1"},
            {"type": 102, "url": f"{BASE}/clip.mp4?_nc_cat=1"},
            {"type": 103, "url": f"{BASE}/clip.mp4?_nc_cat=1"},
        ],
    }


def _page(*nodes: dict) -> str:
    """노드들을 실제 페이지와 같은 모양의 JSON 스크립트 블록에 담는다."""
    blocks = "".join(
        '<script type="application/json" data-sjs>'
        + json.dumps({"require": [["ScheduledServerJS", "handle", None, [{"__bbox": {"result": n}}]]]})
        + "</script>"
        for n in nodes
    )
    return f"<html><head></head><body>{blocks}</body></html>"


# ---- URL 파싱 ------------------------------------------------------------

@pytest.mark.parametrize(
    ("raw", "key", "username"),
    [
        (f"https://www.threads.com/@zuck/post/{CODE}", CODE, "zuck"),
        (f"https://www.threads.net/@zuck/post/{CODE}", CODE, "zuck"),
        (f"https://www.threads.com/zuck/post/{CODE}", CODE, "zuck"),
        (f"https://www.threads.com/t/{CODE}", CODE, None),
        (f"https://threads.com/@zuck/post/{CODE}?xmt=AQ", CODE, "zuck"),
    ],
)
def test_parses_every_post_form(raw: str, key: str, username: str | None) -> None:
    parsed = parse_url(raw)
    assert parsed.platform is Platform.THREADS
    assert parsed.kind is Kind.POST
    assert parsed.key == key
    assert parsed.username == username


def test_threads_net_is_normalized_to_com() -> None:
    # threads.net 은 threads.com 으로 리다이렉트된다 — 정규화 주소도 .com 이어야
    # 캐시 키가 갈라지지 않는다.
    assert "threads.com" in parse_url(f"https://www.threads.net/@zuck/post/{CODE}").url


def test_profile_is_parsed_not_rejected() -> None:
    # 프로필을 UNSUPPORTED 로 떨구면 "지원하지 않는 주소" 라는 엉뚱한 안내가 간다.
    parsed = parse_url("https://www.threads.com/@zuck")
    assert parsed.kind is Kind.PROFILE


@pytest.mark.parametrize(
    "raw",
    [
        "https://www.threads.com/search",
        "https://www.threads.com/@zuck/post/!!!",
        "https://www.threads.com/",
    ],
)
def test_rejects_non_post_urls(raw: str) -> None:
    with pytest.raises(ArchGrabError) as exc:
        parse_url(raw)
    assert exc.value.code is ErrorCode.UNSUPPORTED


# ---- 함정 1: 답글 오염 ---------------------------------------------------

def test_picks_only_the_requested_post_not_replies() -> None:
    """게시글 페이지에는 답글 작성자들의 미디어가 함께 온다.

    실측에서 한 게시글 페이지에 16개 계정 25개 노드가 있었고 남의 답글 미디어가
    6건이었다. code 로 거르지 않으면 모르는 사람 사진을 받는다.
    """
    mine = _image_node(CODE, width=2160, height=2700)
    mine["user"] = {"username": "zuck"}
    reply_a = _image_node("ZZreplyAAA", width=4000, height=4000)   # 더 크다
    reply_a["user"] = {"username": "stranger_a"}
    reply_b = _video_node("ZZreplyBBB")
    reply_b["user"] = {"username": "stranger_b"}

    node = threads_web.pick_node(_page(reply_a, reply_b, mine), CODE)

    assert node["code"] == CODE
    assert (node.get("user") or {}).get("username") == "zuck"
    info = threads_web.to_media_info(
        parse_url(f"https://www.threads.com/t/{CODE}"), node, used_cookies=False
    )
    assert info.uploader == "zuck"
    assert [item.width for item in info.items] == [2160]


# ---- 함정 2: 없는 게시글도 HTTP 200 --------------------------------------

def test_missing_post_is_not_found_even_though_page_returned_ok() -> None:
    other = _image_node("ZZotherAAA")
    with pytest.raises(ArchGrabError) as exc:
        threads_web.pick_node(_page(other), CODE)
    assert exc.value.code is ErrorCode.NOT_FOUND


def test_duplicate_nodes_prefer_the_one_carrying_media() -> None:
    """같은 code 가 여러 블록에 나오고 한쪽은 미디어가 비어 있다."""
    stub = {"code": CODE, "media_type": 1, "image_versions2": {"candidates": []}}
    real = _image_node(CODE)
    assert threads_web.pick_node(_page(stub, real), CODE)["image_versions2"]["candidates"]


# ---- 함정 3: 원본은 크기 토큰 없는 후보 (크롭이 아니다) -------------------

def test_original_image_is_the_untokenized_candidate() -> None:
    node = _image_node(CODE, width=2160, height=2700)
    formats = threads_web._image_formats(node)
    assert len(formats) == 1
    chosen = formats[0]
    assert (chosen.width, chosen.height) == (2160, 2700)
    assert "stp=" not in chosen.url


@pytest.mark.parametrize(("name", "ext"), [("original.webp", "webp"), ("original.jpg", "jpg")])
def test_extension_comes_from_the_url_not_from_an_assumption(name: str, ext: str) -> None:
    """형식을 가정하면 절반이 틀린 이름으로 저장된다.

    실물 두 건에서 하나는 webp, 하나는 jpg 로 왔다. 플랫폼 단위로 단정할 수 없다.
    """
    node = {
        "code": CODE,
        "media_type": 1,
        "original_width": 1203,
        "original_height": 848,
        "image_versions2": {"candidates": [_img(1203, 848, None, name=name)]},
    }
    assert threads_web._image_formats(node)[0].ext == ext


def test_size_token_beats_declared_area_when_the_two_disagree() -> None:
    """규칙은 "크기 토큰이 없는 후보가 원본"이다 — 면적이 가장 큰 후보가 아니다.

    실측한 게시글에서는 두 규칙이 같은 답을 냈다(원본이 면적도 최대였다). 그래서
    면적으로 고르는 구현도 그 표본은 통과한다. 이 테스트는 둘이 **갈라지는**
    경우를 일부러 만들어 규칙 자체를 고정한다 — 나중에 "제일 큰 거 고르면 되지"
    로 단순화되면 크롭·확대본을 집기 시작한다. 실측에서 후보 14개 중 7개가
    크롭(`c0.270.2160.2160a`)이었다.
    """
    node = {
        "code": CODE,
        "media_type": 1,
        "original_width": 1200,
        "original_height": 1500,
        "image_versions2": {
            "candidates": [
                # 토큰이 붙은 쪽이 면적은 더 크다
                _img(2160, 2700, "dst-webp_p2160x2160", name="scaled.webp"),
                _img(1200, 1500, None, name="original.webp"),
            ]
        },
    }
    chosen = threads_web._image_formats(node)[0]
    assert "stp=" not in chosen.url
    assert (chosen.width, chosen.height) == (1200, 1500)


# ---- 함정 4: 동영상은 해상도를 주장하지 않는다 ---------------------------

def test_video_claims_no_resolution_and_collapses_duplicate_types() -> None:
    info = threads_web.to_media_info(
        parse_url(f"https://www.threads.com/t/{CODE}"), _video_node(CODE), used_cookies=False
    )
    item = info.items[0]
    assert item.type == "video"
    # 노드는 1080x1350 이라 하지만 실제 파일은 720x900 이었다 — 적지 않는다.
    assert item.width is None and item.height is None
    # 같은 URL 인 세 type 은 하나로 합쳐야 화질 선택 UI 가 뜨지 않는다
    assert len(item.formats) == 1
    assert item.formats[0].ext == "mp4"


# ---- 캐러셀 혼합 ---------------------------------------------------------

def test_carousel_keeps_images_and_videos_in_order() -> None:
    node = {
        "code": CODE,
        "media_type": 8,
        "user": {"username": "zuck"},
        "caption": {"text": "본문"},
        "taken_at": 1790355021,
        "carousel_media": [
            _image_node(CODE, width=2160, height=2700),
            _video_node(CODE),
            _image_node(CODE, width=1638, height=2048),
        ],
    }
    info = threads_web.to_media_info(
        parse_url(f"https://www.threads.com/@zuck/post/{CODE}"), node, used_cookies=False
    )
    assert [item.type for item in info.items] == ["image", "video", "image"]
    assert [item.index for item in info.items] == [0, 1, 2]
    assert info.missing_items == 0
    assert info.title == "본문"
    assert info.uploader_url == "https://www.threads.com/@zuck"


# ---- 텍스트 전용 ---------------------------------------------------------

def test_text_only_post_says_there_is_nothing_to_download() -> None:
    """엔진 실패가 아니다 — "엔진을 업데이트하세요" 안내가 나가면 안 된다."""
    node = {"code": CODE, "media_type": 19, "caption": {"text": "글만 있음"},
            "image_versions2": {"candidates": []}}
    with pytest.raises(ArchGrabError) as exc:
        threads_web.to_media_info(
            parse_url(f"https://www.threads.com/t/{CODE}"), node, used_cookies=False
        )
    assert exc.value.code is ErrorCode.UNSUPPORTED
    assert exc.value.message == threads_web.TEXT_ONLY


# ---- 요청 주소 ------------------------------------------------------------

def test_engine_requests_the_username_free_form() -> None:
    """주소의 사용자명은 장식이다 — 남의 사용자명을 붙여도 같은 글이 온다.

    사용자명을 쓰지 않는 /t/{code} 로 요청하면 오타·불일치에 영향받지 않는다.
    """
    assert threads_web.post_url(CODE) == f"https://www.threads.com/t/{CODE}"


# ---- 프로필 --------------------------------------------------------------

def test_profile_url_is_rejected_with_a_useful_message() -> None:
    parsed = parse_url("https://www.threads.com/@zuck")
    with pytest.raises(ArchGrabError) as exc:
        threads.extractor.probe(parsed)
    assert exc.value.code is ErrorCode.UNSUPPORTED
    assert exc.value.message == threads.PROFILE_UNSUPPORTED


# ---- 파일명 --------------------------------------------------------------

def test_filenames_are_numbered_for_multi_item_posts() -> None:
    node = {
        "code": CODE,
        "media_type": 8,
        "user": {"username": "zuck"},
        "carousel_media": [_image_node(CODE), _video_node(CODE)],
    }
    parsed = parse_url(f"https://www.threads.com/@zuck/post/{CODE}")
    info = threads_web.to_media_info(parsed, node, used_cookies=False)
    from app.extractors.base import Selection

    names = [name for name, _ in threads.ThreadsExtractor._pairs_for(parsed, info, Selection())]
    assert names == [f"threads_zuck_{CODE}_1.webp", f"threads_zuck_{CODE}_2.mp4"]


def test_single_item_post_has_no_number_suffix() -> None:
    parsed = parse_url(f"https://www.threads.com/@zuck/post/{CODE}")
    node = _image_node(CODE)
    node["user"] = {"username": "zuck"}
    info = threads_web.to_media_info(parsed, node, used_cookies=False)
    from app.extractors.base import Selection

    names = [name for name, _ in threads.ThreadsExtractor._pairs_for(parsed, info, Selection())]
    assert names == [f"threads_zuck_{CODE}.webp"]


# ---- 전송 계층 (실제 네트워크) -------------------------------------------

@pytest.mark.network
def test_real_threads_post_is_readable_without_login() -> None:
    """이 플랫폼을 지원할 수 있는 근거 자체를 확인한다.

    폴백 엔진이 없으므로 이 가정이 깨지면 스레드는 통째로 멈춘다. 그때
    "추출 실패"가 아니라 무엇이 변했는지 바로 보이게 해 둔다.
    """
    from app.core.url import parse_url as _parse

    parsed = _parse(f"https://www.threads.net/@zuck/post/{CODE}")
    # threads.net 입력도 .com 으로 정규화된다
    assert parsed.url.startswith("https://www.threads.com/")

    session = threads_web._session(None)
    try:
        page = session.get(threads_web.post_url(CODE), allow_redirects=True)
    finally:
        session.close()

    assert page.status_code == 200
    assert "/login" not in str(page.url)          # 익명 접근이 막히지 않았다
    assert "image_versions2" in page.text         # 의존하는 구조가 그대로 있다

    node = threads_web.pick_node(page.text, CODE)
    info = threads_web.to_media_info(parsed, node, used_cookies=False)
    assert info.items
    for item in info.items:
        best = item.formats[0]
        assert best.url and best.url.startswith("https://")
        if item.type == "image":
            # 원본(크기 토큰 없는 후보)을 골랐는지
            assert "stp=" not in best.url
            assert item.width and item.height
        else:
            # 동영상은 해상도를 주장하지 않는다
            assert item.width is None and item.height is None


# ---- 공유 링크 (/share/{토큰}) ------------------------------------------

SHARE_TOKEN = "SH4r3tok0n"   # 합성 토큰 — 추적은 주입한 fetch 로 흉내낸다
SHARE_URL = f"https://www.threads.com/share/{SHARE_TOKEN}/"


def test_share_link_is_marked_for_redirect_not_treated_as_a_shortcode() -> None:
    """공유 토큰은 숏코드가 아니다 — 실물에서 9자 토큰이 11자 숏코드를 가리켰다.

    추적하지 않고 엔진에 넘기면 그 토큰으로 글을 찾다가 "찾을 수 없습니다"가
    나간다. 모바일 공유 버튼이 주는 형태라 실사용에서 가장 먼저 부딪친다.
    """
    parsed = parse_url(SHARE_URL)
    assert parsed.platform is Platform.THREADS
    assert parsed.kind is Kind.SHARE
    assert parsed.needs_redirect is True
    assert parsed.key == SHARE_TOKEN


def test_share_link_resolves_to_the_real_post() -> None:
    from app.core.link import follow

    # 실물에서는 302 로 ?xmt=... 추적 파라미터가 붙은 주소가 온다
    target = f"https://www.threads.com/@zuck/post/{CODE}?xmt=AQG0"
    resolved = follow(parse_url(SHARE_URL), lambda _url: (target, ""))

    assert resolved.kind is Kind.POST
    assert resolved.key == CODE
    assert resolved.username == "zuck"
    assert resolved.needs_redirect is False   # 엔진에 넘겨도 안전하다
    assert "xmt=" not in resolved.url         # 추적 파라미터는 제거된다


def test_share_link_falls_back_to_html_escaped_canonical() -> None:
    """스레드의 canonical 은 경로의 @ 를 &#064; 로 내보낸다.

    풀지 않으면 `#` 이 프래그먼트 시작으로 해석돼 경로가 통째로 사라진다. 지금은
    302 가 있어서 본문을 볼 일이 없지만, 리다이렉트가 사라지면 이게 유일한 길이다.
    """
    from app.core.link import follow

    body = (
        '<link rel="canonical" '
        f'href="https://www.threads.com/&#064;zuck/post/{CODE}"/>'
    )
    # 리다이렉트가 없고(공유 주소 그대로) 본문만 있는 상황
    resolved = follow(parse_url(SHARE_URL), lambda url: (url, body))

    assert resolved.kind is Kind.POST
    assert resolved.key == CODE
    assert resolved.username == "zuck"


def test_unfollowed_share_link_is_refused_rather_than_guessed() -> None:
    """추적이 실패하면 공유 토큰을 숏코드로 넘기지 않고 거부한다.

    넘기면 엔진이 그 토큰으로 글을 찾다가 "삭제되었거나 비공개"라는 틀린 안내를
    낸다 — 실제로는 멀쩡한 공개 글이다.
    """
    from app.core.link import follow

    with pytest.raises(ArchGrabError) as exc:
        follow(parse_url(SHARE_URL), lambda url: (url, "<html></html>"))
    assert exc.value.code is ErrorCode.UNSUPPORTED
