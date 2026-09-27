"""X 정규화.

메타데이터 형태는 실제 응답에서 확인한 것을 그대로 옮겼다:
사진 트윗(55_kumamon) 과 동영상 트윗(captainamerica) 을 익명으로 받아 관측했다.

X 가 인스타보다 단순한 이유도 여기서 드러난다 — gallery-dl 이 `type` 을 직접
주고 익명으로도 사진이 내려온다.
"""

from __future__ import annotations

import pytest

from app.core.url import Kind, ParsedUrl, Platform
from app.extractors.gallerydl_engine import GalleryEntry
from app.extractors.x import GALLERY_DL, YT_DLP, engine_order, to_media_info

PARSED = ParsedUrl(
    Platform.X, Kind.TWEET, "2104173204298453306",
    "https://x.com/55_kumamon/status/2104173204298453306", username="55_kumamon",
)

AUTHOR = {"id": 602302847, "name": "55_kumamon", "nick": "くまモン【公式】"}


def photo(num: int = 1, count: int = 1) -> GalleryEntry:
    return GalleryEntry(
        f"https://pbs.twimg.com/media/HTIa-zgaEAAoblx{num}.jpg",
        {"type": "photo", "extension": "jpg", "width": 1477, "height": 1108,
         "num": num, "count": count, "tweet_id": "2104173204298453306",
         "author": AUTHOR, "user": AUTHOR, "content": "ちょっと早いけどおやくま〜☆",
         "date": "2026-09-27 11:36:00"},
    )


def video() -> GalleryEntry:
    return GalleryEntry(
        "https://video.twimg.com/ext_tw_video/1/pu/vid/1280x720/abc.mp4",
        {"type": "video", "extension": "mp4", "width": 1280, "height": 720,
         "duration": 3.17, "num": 1, "count": 1, "author": AUTHOR, "content": "v",
         "date": "2026-09-27 11:36:00"},
    )


class TestEngineOrder:
    def test_gallerydl_is_primary(self) -> None:
        """인스타와 달리 gallery-dl 이 익명으로 사진·동영상을 다 처리한다."""
        assert engine_order() == (GALLERY_DL, YT_DLP)


class TestNormalization:
    def test_photo_tweet(self) -> None:
        info = to_media_info(PARSED, [photo()], {}, used_cookies=False)
        assert len(info.items) == 1
        item = info.items[0]
        assert item.type == "image"
        assert (item.width, item.height) == (1477, 1108)
        assert item.formats[0].ext == "jpg"
        assert item.formats[0].directly_fetchable
        # 사진은 자기 자신이 썸네일이다
        assert item.thumbnail == item.formats[0].url

    def test_video_tweet(self) -> None:
        info = to_media_info(PARSED, [video()], {}, used_cookies=False)
        item = info.items[0]
        assert item.type == "video"
        assert item.duration == 3.17
        # gallery-dl 은 X 동영상에 포스터를 주지 않는다 — 없는 걸 지어내지 않는다
        assert item.thumbnail is None

    def test_multi_photo_tweet_keeps_every_item(self) -> None:
        entries = [photo(n, count=4) for n in (1, 2, 3, 4)]
        info = to_media_info(PARSED, entries, {}, used_cookies=False)
        assert len(info.items) == 4
        assert [i.index for i in info.items] == [0, 1, 2, 3]
        assert all(i.type == "image" for i in info.items)

    def test_animated_gif_is_treated_as_video(self) -> None:
        """X 는 GIF 를 mp4 로 서빙한다."""
        entry = GalleryEntry(
            "https://video.twimg.com/tweet_video/abc.mp4",
            {"type": "animated_gif", "extension": "mp4", "width": 480, "height": 270,
             "author": AUTHOR},
        )
        assert to_media_info(PARSED, [entry], {}, used_cookies=False).items[0].type == "video"

    def test_post_metadata(self) -> None:
        info = to_media_info(PARSED, [photo()], {}, used_cookies=False)
        assert info.uploader == "55_kumamon"
        assert info.uploader_url == "https://x.com/55_kumamon"
        assert info.title == "ちょっと早いけどおやくま〜☆"
        assert info.engine == GALLERY_DL
        assert info.taken_at is not None and info.taken_at.year == 2026

    def test_unknown_type_falls_back_to_extension(self) -> None:
        entry = GalleryEntry(
            "https://pbs.twimg.com/media/x.jpg",
            {"extension": "jpg", "author": AUTHOR},   # type 키 없음
        )
        assert to_media_info(PARSED, [entry], {}, used_cookies=False).items[0].type == "image"


def test_filename_uses_x_prefix() -> None:
    from app.core.models import FormatOption, MediaItem
    from app.extractors.common import media_filename

    info = to_media_info(PARSED, [photo()], {}, used_cookies=False)
    item = MediaItem(id="0", index=0, type="image", formats=[FormatOption(id="o", ext="jpg")])
    name = media_filename("x", PARSED, info, item, item.formats[0], numbered=False)
    assert name == "x_55_kumamon_2104173204298453306.jpg"


@pytest.mark.parametrize("raw", ["2026-09-27 11:36:00", "2026-09-27T11:36:00Z", 1789000000])
def test_timestamp_formats(raw: object) -> None:
    from app.extractors.common import parse_timestamp

    assert parse_timestamp(raw) is not None
