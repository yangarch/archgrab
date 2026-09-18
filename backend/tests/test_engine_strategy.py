"""엔진 선택과 이미지 포맷 합성.

이 테스트들은 실제로 있었던 오진을 고정한다: curl_cffi 가 없어서 yt-dlp 의
위장 타겟이 0개였고, 그래서 인스타의 비로그인 GraphQL 경로가 조용히 비활성됐다.
그 결과 공개 게시글까지 "쿠키 필요"로 오진했다. 실제로는 쿠키 없이도 된다.
"""

from __future__ import annotations

import pytest

from app.core.models import FormatOption, MediaItem
from app.extractors import ytdlp_engine
from app.extractors.instagram import GALLERY_DL, YT_DLP, _pick_format, engine_order


class TestEngineOrder:
    def test_without_cookies_only_ytdlp(self) -> None:
        """gallery-dl 은 익명 인스타 접근이 불가능하므로 아예 부르지 않는다."""
        assert engine_order(has_cookies=False) == (YT_DLP,)

    def test_with_cookies_gallerydl_first(self) -> None:
        """쿠키가 있으면 이미지·캐러셀 메타데이터가 정확한 gallery-dl 을 먼저 쓴다."""
        assert engine_order(has_cookies=True) == (GALLERY_DL, YT_DLP)


class TestImageFormatSynthesis:
    """yt-dlp 는 이미지를 formats 가 아니라 thumbnails 에 담는다."""

    def test_largest_candidate_becomes_the_original(self) -> None:
        entry = {
            "formats": [],
            "thumbnails": [
                {"url": "https://cdn.example/s.jpg", "width": 320, "height": 400},
                {"url": "https://cdn.example/l.jpg", "width": 1440, "height": 1800},
                {"url": "https://cdn.example/m.jpg", "width": 640, "height": 800},
            ],
        }
        formats = ytdlp_engine._formats(entry)
        assert len(formats) == 1
        original = formats[0]
        assert (original.width, original.height) == (1440, 1800)
        assert original.ext == "jpg"
        assert original.directly_fetchable
        assert ytdlp_engine._media_type(entry, formats) == "image"

    def test_video_formats_win_over_thumbnails(self) -> None:
        entry = {
            "formats": [{
                "format_id": "dash-1", "ext": "mp4", "width": 1080, "height": 1920,
                "vcodec": "h264", "acodec": "aac", "url": "https://cdn.example/v.mp4",
                "protocol": "https",
            }],
            "thumbnails": [{"url": "https://cdn.example/poster.jpg", "width": 640, "height": 1138}],
        }
        formats = ytdlp_engine._formats(entry)
        assert [f.ext for f in formats] == ["mp4"]
        assert ytdlp_engine._media_type(entry, formats) == "video"

    def test_storyboards_are_dropped(self) -> None:
        entry = {
            "formats": [
                {"format_id": "sb0", "ext": "mhtml", "vcodec": "none", "acodec": "none"},
                {"format_id": "0", "ext": "mp4", "vcodec": "h264", "acodec": "aac",
                 "url": "https://cdn.example/v.mp4", "protocol": "https"},
            ],
            "thumbnails": [],
        }
        assert [f.id for f in ytdlp_engine._formats(entry)] == ["0"]


class TestFormatSelection:
    def _item(self, *formats: FormatOption) -> MediaItem:
        """엔진이 정렬해 넘긴 상태를 흉내낸다 (좋은 것이 먼저)."""
        ranked = sorted(formats, key=ytdlp_engine._rank, reverse=True)
        return MediaItem(id="0", index=0, type="video", formats=ranked)

    def test_prefers_directly_fetchable_over_dash(self) -> None:
        """같은 게시글에 DASH 와 프로그레시브가 같이 오면 직접 받을 수 있는 쪽."""
        dash = FormatOption(id="dash", ext="mp4", width=1080, height=1920,
                            url="https://cdn.example/m.mpd", protocol="dash")
        progressive = FormatOption(id="prog", ext="mp4", width=1080, height=1920,
                                   url="https://cdn.example/v.mp4", protocol="https")
        assert _pick_format(self._item(dash, progressive), None).id == "prog"

    def test_falls_back_to_dash_when_nothing_else(self) -> None:
        dash = FormatOption(id="dash", ext="mp4", url="https://cdn.example/m.mpd",
                            protocol="dash")
        assert _pick_format(self._item(dash), None).id == "dash"

    def test_explicit_choice_is_honored(self) -> None:
        small = FormatOption(id="small", ext="mp4", width=480, height=854,
                             url="https://cdn.example/s.mp4", protocol="https")
        large = FormatOption(id="large", ext="mp4", width=1080, height=1920,
                             url="https://cdn.example/l.mp4", protocol="https")
        item = self._item(small, large)
        assert _pick_format(item, "small").id == "small"
        assert _pick_format(item, None).id == "large"

    def test_no_formats_returns_none(self) -> None:
        assert _pick_format(self._item(), None) is None


def test_signed_urls_never_reach_the_api_response() -> None:
    """포맷의 CDN 주소는 내부용이다 — 직렬화에 섞이면 안 된다."""
    fmt = FormatOption(id="x", ext="mp4", url="https://cdn.example/secret.mp4?sig=abc")
    assert "url" not in fmt.model_dump()
    assert "sig=abc" not in str(fmt.model_dump())


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://cdn.example/a.jpg?ig_cache_key=xyz", "jpg"),
        ("https://cdn.example/a.webp", "webp"),
        ("https://cdn.example/noext", "jpg"),
    ],
)
def test_extension_from_url(url: str, expected: str) -> None:
    assert ytdlp_engine._ext_from_url(url) == expected


def test_audio_only_never_sorts_first() -> None:
    """화면이 보여주는 formats[0] 이 오디오 전용이면 안 된다 (실제로 났던 버그)."""
    entry = {
        "formats": [
            {"format_id": "audio", "ext": "m4a", "vcodec": "none", "acodec": "aac",
             "url": "https://cdn.example/a.m4a", "protocol": "https",
             "format_note": "DASH audio"},
            {"format_id": "video", "ext": "mp4", "width": 720, "height": 1280,
             "vcodec": "h264", "acodec": "aac", "url": "https://cdn.example/v.mp4",
             "protocol": "https"},
        ],
        "thumbnails": [],
    }
    formats = ytdlp_engine._formats(entry)
    assert formats[0].id == "video", [f.id for f in formats]


class TestProgressiveFormatsSurvive:
    """인스타의 progressive mp4 는 코덱을 보고하지 않는다 — 버리면 무음 파일이 나온다.

    실제로 났던 버그: '두 코덱이 모두 없으면 버린다'는 필터가 영상+음성 완결
    포맷을 버려서, DASH 영상전용을 받아 오디오 트랙이 없는 파일이 만들어졌다.
    """

    ENTRY = {
        "formats": [
            {"format_id": "1", "ext": "mp4", "vcodec": None, "acodec": None,
             "url": "https://cdn.example/prog1.mp4", "protocol": "https"},
            {"format_id": "dash-a", "ext": "m4a", "vcodec": "none", "acodec": "mp4a.40.5",
             "url": "https://cdn.example/a.m4a", "protocol": "https",
             "format_note": "DASH audio"},
            {"format_id": "dash-v", "ext": "mp4", "width": 720, "height": 1280,
             "vcodec": "avc1.64001f", "acodec": "none",
             "url": "https://cdn.example/v.mp4", "protocol": "https",
             "format_note": "DASH video"},
        ],
        "thumbnails": [],
    }

    def test_progressive_format_is_kept(self) -> None:
        ids = [f.id for f in ytdlp_engine._formats(self.ENTRY)]
        assert "1" in ids, ids

    def test_highest_resolution_wins_even_if_it_needs_mux(self) -> None:
        formats = ytdlp_engine._formats(self.ENTRY)
        assert formats[0].id == "dash-v"
        assert formats[0].needs_mux

    def test_audio_only_sorts_last(self) -> None:
        assert ytdlp_engine._formats(self.ENTRY)[-1].id == "dash-a"

    def test_mux_is_visible_in_the_label(self) -> None:
        """사용자가 무음 파일을 예상하지 않도록 라벨에 드러나야 한다."""
        assert "음성 합침" in ytdlp_engine._formats(self.ENTRY)[0].label

    def test_url_without_media_is_dropped(self) -> None:
        entry = {"formats": [{"format_id": "x", "ext": "mp4"}], "thumbnails": []}
        assert ytdlp_engine._formats(entry) == []


def test_outtmpl_uses_project_naming_and_escapes_percent() -> None:
    """yt-dlp 가 받더라도 파일명은 우리 규칙을 따라야 한다 (zip·README 와 일치)."""
    from app.core.models import MediaInfo
    from app.core.url import Kind, ParsedUrl, Platform
    from app.extractors.instagram import _outtmpl

    parsed = ParsedUrl(Platform.INSTAGRAM, Kind.POST, "DPWO1aRD_Ju",
                       "https://www.instagram.com/p/DPWO1aRD_Ju/")
    media = MediaInfo(platform=Platform.INSTAGRAM, kind=Kind.POST,
                      source_url=parsed.url, key=parsed.key, uploader="100%_user")
    tmpl = _outtmpl(parsed, media)
    assert tmpl.startswith("instagram_100%%_user_DPWO1aRD_Ju")
    assert tmpl.endswith(".%(ext)s")


def test_dimensionless_formats_are_distinguishable() -> None:
    entry = {
        "formats": [
            {"format_id": "1", "ext": "mp4", "url": "https://cdn.example/1.mp4",
             "protocol": "https"},
            {"format_id": "2", "ext": "mp4", "url": "https://cdn.example/2.mp4",
             "protocol": "https"},
        ],
        "thumbnails": [],
    }
    labels = [f.label for f in ytdlp_engine._formats(entry)]
    assert len(set(labels)) == 2, labels
