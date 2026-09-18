"""프론트가 플랫폼을 몰라도 되게 만드는 공통 모델."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, computed_field

from app.core.url import Kind, Platform

MediaType = Literal["video", "image", "audio"]


def _human_size(size: int | None) -> str | None:
    if not size:
        return None
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f}{unit}" if unit == "B" else f"{value:.1f}{unit}"
        value /= 1024
    return None


class FormatOption(BaseModel):
    """내려받을 수 있는 하나의 원본 스트림."""

    id: str
    ext: str
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    filesize: int | None = None          # 정확치 없으면 추정치
    filesize_approx: bool = False
    vcodec: str | None = None
    acodec: str | None = None
    note: str | None = None
    needs_mux: bool = False              # 영상+음성 분리 스트림 (무손실 mux 필요)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def label(self) -> str:
        bits: list[str] = []
        if self.width and self.height:
            bits.append(f"{self.width}×{self.height}")
        elif self.height:
            bits.append(f"{self.height}p")
        bits.append(self.ext)
        if self.fps and self.fps >= 50:
            bits.append(f"{self.fps:.0f}fps")
        size = _human_size(self.filesize)
        if size:
            bits.append(f"~{size}" if self.filesize_approx else size)
        if self.note:
            bits.append(self.note)
        return " · ".join(bits)


class MediaItem(BaseModel):
    """게시글 안의 미디어 한 개. 캐러셀이면 여러 개가 들어온다."""

    id: str
    index: int
    type: MediaType
    title: str | None = None
    thumbnail: str | None = None
    duration: float | None = None
    width: int | None = None
    height: int | None = None
    formats: list[FormatOption] = Field(default_factory=list)

    @property
    def best_format(self) -> FormatOption | None:
        """원본 우선: 해상도 → 파일크기 순. 재인코딩 선택지는 애초에 만들지 않는다."""
        if not self.formats:
            return None
        return max(
            self.formats,
            key=lambda f: ((f.width or 0) * (f.height or 0), f.filesize or 0),
        )


class MediaInfo(BaseModel):
    """resolve 응답. 메타데이터만 담고 실제 바이트는 받지 않는다."""

    platform: Platform
    kind: Kind
    source_url: str
    key: str
    title: str | None = None
    uploader: str | None = None
    uploader_url: str | None = None
    description: str | None = None
    taken_at: datetime | None = None
    items: list[MediaItem] = Field(default_factory=list)
    engine: str = ""
    used_cookies: bool = False


class JobStatus(StrEnum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    PACKAGING = "packaging"
    DONE = "done"
    ERROR = "error"
    CANCELED = "canceled"


class JobCreate(BaseModel):
    url: str
    item_ids: list[str] | None = None          # None 이면 전체
    format_ids: dict[str, str] | None = None   # item_id → format_id
    audio_only: bool = False


class JobFile(BaseModel):
    name: str
    size: int
    token: str                                  # GET /api/files/{token}
    content_type: str = "application/octet-stream"


class JobProgress(BaseModel):
    done_bytes: int = 0
    total_bytes: int | None = None
    percent: float = 0.0
    current: str | None = None                  # 지금 받고 있는 파일명
    index: int = 0
    count: int = 0

class Job(BaseModel):
    id: str
    status: JobStatus
    url: str
    platform: Platform | None = None
    title: str | None = None
    progress: JobProgress = Field(default_factory=JobProgress)
    files: list[JobFile] = Field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime
    finished_at: datetime | None = None
    expires_at: datetime | None = None
