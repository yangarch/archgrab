"""gallery-dl 어댑터 — 인스타 이미지·캐러셀·스토리의 주력 엔진.

PATH 의 실행 파일을 찾지 않고 현재 인터프리터의 모듈로 호출한다. venv·컨테이너
어디서 띄워도 같은 환경이 잡히고 PATH 가 비어 있어도 동작한다.

`-j` 는 파일을 받지 않고 JSON 만 뽑는다. 출력은 메시지 배열이고 각 원소는
  [3, url, meta]  파일 하나
  [2, meta]       게시글 메타
  [6, url, meta]  하위 추출 대기 (프로필 등)
  [-1, {...}]     에러
**주의: gallery-dl 의 DataJob 은 추출이 실패해도 종료코드 0 을 반환한다.**
그래서 exit code 가 아니라 -1 항목을 봐야 한다.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.config import get_settings
from app.core.errors import ErrorCode, ArchGrabError, from_engine_error
from app.core.security import mask_secrets

BASE_CMD: tuple[str, ...] = (sys.executable, "-m", "gallery_dl")

MSG_ERROR = -1
MSG_DIRECTORY = 2
MSG_URL = 3
MSG_QUEUE = 6

VIDEO_EXTENSIONS = frozenset({"mp4", "mov", "m4v", "webm", "mkv"})
AUDIO_EXTENSIONS = frozenset({"m4a", "mp3", "aac", "opus", "ogg"})


@lru_cache
def version() -> str | None:
    try:
        result = subprocess.run(  # noqa: S603
            [*BASE_CMD, "--version"], capture_output=True, text=True, timeout=20
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    lines = (result.stdout or result.stderr).strip().splitlines()
    return lines[0].strip() if lines else None


def is_available() -> bool:
    return version() is not None


@dataclass(frozen=True, slots=True)
class GalleryEntry:
    """gallery-dl 이 내놓은 파일 하나 — 원본 CDN 주소와 메타데이터."""

    url: str
    meta: dict

    @property
    def extension(self) -> str:
        ext = str(self.meta.get("extension") or "").lstrip(".").lower()
        if ext:
            return ext
        tail = self.url.split("?")[0].rsplit(".", 1)
        return tail[-1].lower() if len(tail) == 2 and len(tail[-1]) <= 5 else "bin"

    @property
    def media_type(self) -> str:
        if self.extension in VIDEO_EXTENSIONS:
            return "video"
        if self.extension in AUDIO_EXTENSIONS:
            return "audio"
        # typename 은 인스타 전용 힌트 (GraphVideo 등)
        if "video" in str(self.meta.get("typename") or "").lower():
            return "video"
        return "image"

    @property
    def num(self) -> int:
        try:
            return int(self.meta.get("num") or 0)
        except (TypeError, ValueError):
            return 0

    def dimension(self, key: str) -> int | None:
        value = self.meta.get(key)
        return int(value) if isinstance(value, int | float) and value else None


def _build_cmd(url: str, cookies: Path | None) -> list[str]:
    settings = get_settings()
    # --config-ignore: 사용자 전역 gallery-dl 설정이 동작을 바꾸지 못하게 한다.
    cmd = [*BASE_CMD, "--config-ignore", "-j", "-R", "3"]
    if cookies is not None:
        cmd += ["--cookies", str(cookies)]
    if settings.proxy:
        cmd += ["--proxy", settings.proxy]
    cmd.append(url)
    return cmd


def dump(url: str, cookies: Path | None = None) -> tuple[list[GalleryEntry], dict]:
    """(파일 목록, 게시글 메타). 추출 실패는 ArchGrabError 로 올린다."""
    settings = get_settings()
    if not is_available():
        raise ArchGrabError(
            ErrorCode.ENGINE_FAILED,
            "gallery-dl 이 설치되지 않았습니다. `make install` 을 실행해주세요.",
        )

    try:
        result = subprocess.run(  # noqa: S603
            _build_cmd(url, cookies),
            capture_output=True,
            text=True,
            timeout=settings.engine_timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise ArchGrabError(ErrorCode.TIMEOUT, detail="gallery-dl 응답 없음") from exc
    except OSError as exc:
        raise ArchGrabError(ErrorCode.ENGINE_FAILED, detail=str(exc)) from exc

    stderr = mask_secrets(result.stderr or "")

    try:
        messages = json.loads(result.stdout or "[]")
    except json.JSONDecodeError as exc:
        # JSON 이 안 나왔으면 stderr 가 유일한 단서다
        raise from_engine_error(stderr or "gallery-dl 출력을 해석할 수 없습니다") from exc

    entries: list[GalleryEntry] = []
    post_meta: dict = {}
    queued = 0

    for message in messages:
        if not isinstance(message, list) or not message:
            continue
        kind = message[0]
        if kind == MSG_ERROR and len(message) >= 2:
            payload = message[1] if isinstance(message[1], dict) else {}
            raise from_engine_error(
                f"{payload.get('error', '')}: {payload.get('message', '')}".strip(": ")
                or stderr
            )
        if kind == MSG_DIRECTORY and len(message) >= 2 and isinstance(message[1], dict):
            post_meta = post_meta or message[1]
        elif kind == MSG_URL and len(message) >= 3 and isinstance(message[2], dict):
            entries.append(GalleryEntry(str(message[1]), message[2]))
        elif kind == MSG_QUEUE:
            queued += 1

    if not entries:
        if queued:
            raise ArchGrabError(
                ErrorCode.UNSUPPORTED,
                "여러 게시글이 들어 있는 주소입니다. 개별 게시글 링크를 넣어주세요.",
            )
        raise from_engine_error(stderr or "내려받을 미디어를 찾지 못했습니다")

    entries.sort(key=lambda e: e.num)
    return entries, post_meta
