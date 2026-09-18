"""gallery-dl JSON 해석 — 실제 네트워크 없이 형식 계약을 고정한다.

메시지 형식은 설치된 gallery_dl.job.DataJob 에서 확인한 것:
  [3, url, meta] 파일 / [2, meta] 게시글 / [-1, {...}] 에러
"""

from __future__ import annotations

import json
import subprocess

import pytest

from app.core.errors import ErrorCode, ArchGrabError
from app.extractors import gallerydl_engine
from app.extractors.instagram import _to_media_info
from app.core.url import parse_url

CAROUSEL = [
    [2, {"username": "someone", "post_shortcode": "CxYzAbC123", "description": "여행 사진"}],
    [3, "https://scontent.example/1.jpg", {
        "num": 1, "extension": "jpg", "width": 1440, "height": 1800,
        "username": "someone", "post_shortcode": "CxYzAbC123",
        "display_url": "https://scontent.example/1.jpg", "typename": "GraphImage",
    }],
    [3, "https://scontent.example/2.mp4", {
        "num": 2, "extension": "mp4", "width": 1080, "height": 1920, "duration": 14.2,
        "username": "someone", "post_shortcode": "CxYzAbC123",
        "display_url": "https://scontent.example/2_poster.jpg", "typename": "GraphVideo",
    }],
]


def _fake_run(payload: list, *, stderr: str = "", returncode: int = 0):
    def runner(cmd, **kwargs):  # noqa: ANN001, ARG001
        return subprocess.CompletedProcess(cmd, returncode, json.dumps(payload), stderr)
    return runner


@pytest.fixture(autouse=True)
def _available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gallerydl_engine, "is_available", lambda: True)


def test_carousel_entries_are_ordered_and_typed(
    env, monkeypatch: pytest.MonkeyPatch  # noqa: ANN001, ARG001
) -> None:
    monkeypatch.setattr(subprocess, "run", _fake_run(CAROUSEL))
    entries, post = gallerydl_engine.dump("https://www.instagram.com/p/CxYzAbC123/")

    assert [e.media_type for e in entries] == ["image", "video"]
    assert [e.num for e in entries] == [1, 2]
    assert post["username"] == "someone"


def test_normalized_media_info(env, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001, ARG001
    monkeypatch.setattr(subprocess, "run", _fake_run(CAROUSEL))
    parsed = parse_url("https://www.instagram.com/p/CxYzAbC123/")
    entries, post = gallerydl_engine.dump(parsed.url)
    info = _to_media_info(parsed, entries, post, used_cookies=False)

    assert info.uploader == "someone"
    assert len(info.items) == 2
    image, video = info.items
    assert (image.type, image.width, image.height) == ("image", 1440, 1800)
    assert video.type == "video" and video.duration == 14.2
    # 동영상 썸네일은 포스터 이미지를 쓴다
    assert video.thumbnail == "https://scontent.example/2_poster.jpg"
    # 포맷은 원본 하나뿐이어야 한다 — 화질 열거나 재인코딩 선택지를 만들지 않는다
    assert [f.id for f in image.formats] == ["original"]
    assert "1440×1800" in image.formats[0].label


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("login required", ErrorCode.LOGIN_REQUIRED),
        ("HTTP redirect to login page", ErrorCode.LOGIN_REQUIRED),
        ("Private account", ErrorCode.PRIVATE),
        ("404 Not Found", ErrorCode.NOT_FOUND),
        ("429 Too Many Requests", ErrorCode.RATE_LIMITED),
        ("something entirely new", ErrorCode.ENGINE_FAILED),
    ],
)
def test_error_messages_are_classified(
    env, monkeypatch: pytest.MonkeyPatch, message: str, expected: ErrorCode  # noqa: ANN001, ARG001
) -> None:
    payload = [[-1, {"error": "HttpError", "message": message}]]
    monkeypatch.setattr(subprocess, "run", _fake_run(payload))
    with pytest.raises(ArchGrabError) as caught:
        gallerydl_engine.dump("https://www.instagram.com/p/CxYzAbC123/")
    assert caught.value.code is expected


def test_exit_code_zero_with_error_entry_still_fails(
    env, monkeypatch: pytest.MonkeyPatch  # noqa: ANN001, ARG001
) -> None:
    """gallery-dl 은 추출 실패에도 종료코드 0 을 준다 — 이 경우를 놓치면 빈 작업이 생긴다."""
    payload = [[-1, {"error": "AuthorizationError", "message": "login required"}]]
    monkeypatch.setattr(subprocess, "run", _fake_run(payload, returncode=0))
    with pytest.raises(ArchGrabError) as caught:
        gallerydl_engine.dump("https://www.instagram.com/p/CxYzAbC123/")
    assert caught.value.code is ErrorCode.LOGIN_REQUIRED


def test_profile_url_with_only_queued_children_is_rejected(
    env, monkeypatch: pytest.MonkeyPatch  # noqa: ANN001, ARG001
) -> None:
    payload = [[6, "https://www.instagram.com/p/AAA/", {}], [6, "https://www.instagram.com/p/BBB/", {}]]
    monkeypatch.setattr(subprocess, "run", _fake_run(payload))
    with pytest.raises(ArchGrabError) as caught:
        gallerydl_engine.dump("https://www.instagram.com/someone/")
    assert caught.value.code is ErrorCode.UNSUPPORTED
