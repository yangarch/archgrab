"""내려받은 파일을 전달 가능한 형태로 정리한다.

여러 개면 zip 을 **추가로** 만든다. 개별 파일도 그대로 남겨서 한 장만 필요한
경우 zip 을 풀 필요가 없게 한다. 어느 쪽이든 TTL 이 지나면 함께 지워진다.
"""

from __future__ import annotations

import mimetypes
import zipfile
from pathlib import Path

from app.core.models import JobFile
from app.media.storage import make_token, safe_name


def _content_type(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


def make_zip(dest: Path, base_name: str, paths: list[Path]) -> Path:
    target = dest / safe_name(f"{base_name}.zip")
    # 이미 압축된 미디어라 재압축 이득이 없다 — 저장만 해서 CPU 를 아낀다.
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_STORED) as archive:
        for path in paths:
            archive.write(path, arcname=path.name)
    return target


def to_job_files(job_id: str, paths: list[Path]) -> list[JobFile]:
    files: list[JobFile] = []
    for path in paths:
        if not path.is_file():
            continue
        files.append(
            JobFile(
                name=path.name,
                size=path.stat().st_size,
                token=make_token(job_id, path.name),
                content_type=_content_type(path),
            )
        )
    return files
