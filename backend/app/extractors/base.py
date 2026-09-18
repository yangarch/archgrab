"""추출 엔진 공통 계약.

엔진 호출은 전부 블로킹(서브프로세스·동기 HTTP)이라 동기 함수로 두고,
호출하는 쪽에서 asyncio.to_thread 로 감싼다.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from app.core.models import MediaInfo
from app.core.url import ParsedUrl


@dataclass(slots=True)
class ProgressEvent:
    done_bytes: int = 0
    total_bytes: int | None = None
    current: str | None = None
    index: int = 0
    count: int = 0


ProgressCallback = Callable[[ProgressEvent], None]


def noop_progress(event: ProgressEvent) -> None:  # noqa: ARG001
    return None


@dataclass(frozen=True, slots=True)
class Selection:
    """어떤 항목을 어떤 포맷으로 받을지."""

    item_ids: frozenset[str] | None = None            # None 이면 전체
    format_ids: Mapping[str, str] = field(default_factory=dict)
    audio_only: bool = False

    def wants(self, item_id: str) -> bool:
        return self.item_ids is None or item_id in self.item_ids

    def format_for(self, item_id: str) -> str | None:
        return self.format_ids.get(item_id)


class Extractor(Protocol):
    name: str

    def probe(self, parsed: ParsedUrl) -> MediaInfo:
        """메타데이터만 가져온다. 바이트는 받지 않는다."""
        ...

    def download(
        self,
        parsed: ParsedUrl,
        selection: Selection,
        dest: Path,
        progress: ProgressCallback = noop_progress,
    ) -> list[Path]:
        """dest 에 파일을 받고 경로 목록을 돌려준다."""
        ...
