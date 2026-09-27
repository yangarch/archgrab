"""유튜브 포맷 정리.

실측 기준 (dQw4w9WgXcQ): 한 영상에 포맷 44개, 완결(영상+음성) 포맷은 0개.
같은 해상도가 webm/mp4/HLS 로 중복되고, 4K 는 webm 342MB vs mp4 229MB 다.
정리하지 않으면 화면이 쓸 수 없고 기본 선택도 더 크고 호환성 낮은 쪽이 된다.
"""

from __future__ import annotations

from app.core.models import FormatOption
from app.extractors.youtube import AUDIO_NOTE, group_formats, pick_audio


def video(fid: str, height: int, ext: str, size: int, protocol: str = "https") -> FormatOption:
    return FormatOption(
        id=fid, ext=ext, width=height * 16 // 9, height=height,
        vcodec="avc1" if ext == "mp4" else "vp9", acodec="none",
        filesize=size, needs_mux=True,
        url=f"https://cdn.example/{fid}", protocol=protocol,
    )


def audio(fid: str, ext: str, size: int) -> FormatOption:
    return FormatOption(
        id=fid, ext=ext, vcodec="none", acodec="mp4a.40.2" if ext == "m4a" else "opus",
        filesize=size, url=f"https://cdn.example/{fid}", protocol="https",
    )


REAL_SHAPE = [
    video("313", 2160, "webm", 342_000_000),
    video("401", 2160, "mp4", 229_000_000),
    video("625", 2160, "mp4", 0, protocol="m3u8_native"),
    video("137", 1080, "mp4", 77_000_000),
    video("248", 1080, "webm", 29_000_000),
    video("134", 360, "mp4", 8_000_000),
    audio("140", "m4a", 3_300_000),
    audio("251", "webm", 3_400_000),
]


class TestGrouping:
    def test_one_row_per_resolution(self) -> None:
        grouped = group_formats(REAL_SHAPE)
        heights = [f.height for f in grouped if f.height]
        assert len(heights) == len(set(heights)), heights
        # 2160 / 1080 / 360 + 오디오 1
        assert len(grouped) == 4

    def test_mp4_wins_at_the_same_resolution(self) -> None:
        """4K 에서 webm 342MB 대신 mp4 229MB 를 고른다 — 더 작고 호환성도 좋다."""
        top = group_formats(REAL_SHAPE)[0]
        assert top.id == "401"
        assert top.ext == "mp4"

    def test_hls_loses_to_directly_fetchable(self) -> None:
        assert all(f.protocol != "m3u8_native" for f in group_formats(REAL_SHAPE))

    def test_sorted_high_to_low(self) -> None:
        heights = [f.height for f in group_formats(REAL_SHAPE) if f.height]
        assert heights == sorted(heights, reverse=True)

    def test_audio_only_option_is_last_and_labelled(self) -> None:
        last = group_formats(REAL_SHAPE)[-1]
        assert last.note == AUDIO_NOTE
        assert last.vcodec == "none"

    def test_displayed_size_includes_the_audio_that_gets_merged(self) -> None:
        """영상전용 크기만 보여주면 실제 파일과 어긋난다 (실측: 8.0MB 표시 → 11.8MB)."""
        row = next(f for f in group_formats(REAL_SHAPE) if f.height == 360)
        assert row.filesize == 8_000_000 + 3_300_000
        assert row.filesize_approx

        # 라벨은 합계를 보여줘야 한다. 영상전용 크기가 그대로 보이면 안 된다.
        video_only_label = f"{8_000_000 / 1024 / 1024:.1f}MB"      # 7.6MB
        merged_label = f"{11_300_000 / 1024 / 1024:.1f}MB"         # 10.8MB
        assert merged_label in row.label
        assert video_only_label not in row.label

    def test_no_video_formats_still_offers_audio(self) -> None:
        grouped = group_formats([audio("140", "m4a", 3_300_000)])
        assert len(grouped) == 1 and grouped[0].note == AUDIO_NOTE


class TestAudioChoice:
    def test_mp4_gets_m4a_not_opus(self) -> None:
        """opus-in-mp4 는 QuickTime·iOS 기본 재생기가 열지 못하는 경우가 많다."""
        picked = pick_audio(REAL_SHAPE, container="mp4")
        assert picked is not None and picked.ext == "m4a"

    def test_without_container_takes_the_largest(self) -> None:
        picked = pick_audio(REAL_SHAPE)
        assert picked is not None and picked.id == "251"

    def test_none_when_no_audio(self) -> None:
        assert pick_audio([video("134", 360, "mp4", 1)]) is None


class TestBotCheckFallback:
    """유튜브는 데이터센터 IP 를 봇으로 본다. 집에서는 되는데 서버에서만 실패한다.

    실측(2026-09): 동작하는 대체 클라이언트는 android 계열뿐이고 360p 로 제한된다.
    구제는 되지만 화질을 깎으므로 조용히 넘어가면 안 된다.
    """

    def _boom(self, message: str):  # noqa: ANN202
        from app.core.errors import ArchGrabError, ErrorCode

        def raiser(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
            raise ArchGrabError(ErrorCode.ENGINE_FAILED, detail=message)

        return raiser

    def test_non_bot_errors_are_not_retried(self, monkeypatch) -> None:  # noqa: ANN001
        """봇 감지가 아닌 실패까지 여러 클라이언트로 재시도하면 시간만 버린다."""
        import pytest

        from app.core.errors import ArchGrabError
        from app.extractors import youtube, ytdlp_engine

        calls = []

        def raiser(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
            calls.append(kwargs.get("player_clients"))
            self._boom("Video unavailable")()

        monkeypatch.setattr(ytdlp_engine, "extract", raiser)
        from app.core.url import Kind, ParsedUrl, Platform

        parsed = ParsedUrl(Platform.YOUTUBE, Kind.VIDEO, "x", "https://youtu.be/x")
        with pytest.raises(ArchGrabError):
            youtube._extract(parsed, None)
        assert len(calls) == 1, calls

    def test_bot_check_falls_back_and_reports_which_client(self, monkeypatch) -> None:  # noqa: ANN001
        from app.core.url import Kind, ParsedUrl, Platform
        from app.extractors import youtube, ytdlp_engine

        attempts = []

        def maybe(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
            clients = kwargs.get("player_clients")
            attempts.append(clients)
            if clients is None:
                self._boom("Sign in to confirm you're not a bot")()
            return {"title": "t", "formats": []}

        monkeypatch.setattr(ytdlp_engine, "extract", maybe)
        parsed = ParsedUrl(Platform.YOUTUBE, Kind.VIDEO, "x", "https://youtu.be/x")
        raw, degraded = youtube._extract(parsed, None)
        assert raw["title"] == "t"
        assert degraded == "android_vr"
        assert len(attempts) == 2

    def test_degraded_fallback_is_announced(self) -> None:
        """360p 로 떨어졌으면 화면에 이유가 떠야 한다."""
        assert "360p" in youtube_degraded_notice()
        assert "쿠키" in youtube_degraded_notice()


def youtube_degraded_notice() -> str:
    from app.extractors.youtube import DEGRADED_NOTICE

    return DEGRADED_NOTICE.format(client="android_vr")
