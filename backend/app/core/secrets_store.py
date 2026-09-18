"""플랫폼별 cookies.txt 를 암호화해 보관한다.

키는 SECRET_KEY 에서 유도하므로 별도 키 파일이 없다. 같은 호스트가 털리면 함께
털리는 수준의 보호지만, 백업·볼륨 복사·실수로 인한 평문 유출은 막아준다.
"""

from __future__ import annotations

import base64
import hashlib
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings
from app.core.errors import ErrorCode, ArchGrabError

SUPPORTED = ("instagram", "x", "youtube")


def _fernet() -> Fernet:
    secret = get_settings().secret_key
    if not secret:
        raise RuntimeError("ARCHGRAB_SECRET_KEY 가 설정되지 않았습니다 (.env 확인)")
    key = hashlib.scrypt(
        secret.encode(), salt=b"archgrab.cookies", n=2**14, r=8, p=1, dklen=32
    )
    return Fernet(base64.urlsafe_b64encode(key))


def _path(platform: str) -> Path:
    settings = get_settings()
    settings.ensure_dirs()
    return settings.secrets_dir / f"{platform}.cookies.enc"


@dataclass(frozen=True, slots=True)
class CookieStatus:
    platform: str
    present: bool
    updated_at: float | None = None
    entries: int = 0
    earliest_expiry: float | None = None

    @property
    def expired(self) -> bool:
        return self.earliest_expiry is not None and self.earliest_expiry < time.time()


def _validate(text: str) -> tuple[int, float | None]:
    """Netscape cookie 파일인지 확인하고 (유효 줄 수, 가장 이른 만료시각) 반환."""
    entries = 0
    earliest: float | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        fields = stripped.split("\t")
        if len(fields) < 7:
            continue
        entries += 1
        try:
            expiry = float(fields[4])
        except ValueError:
            continue
        if expiry > 0 and (earliest is None or expiry < earliest):
            earliest = expiry
    if entries == 0:
        raise ArchGrabError(
            ErrorCode.UNSUPPORTED,
            "Netscape 형식의 cookies.txt 가 아닙니다. 브라우저 확장으로 내보낸 파일을 넣어주세요.",
        )
    return entries, earliest


def save_cookies(platform: str, text: str) -> CookieStatus:
    if platform not in SUPPORTED:
        raise ArchGrabError(ErrorCode.UNSUPPORTED, f"알 수 없는 플랫폼: {platform}")
    entries, earliest = _validate(text)
    target = _path(platform)
    target.write_bytes(_fernet().encrypt(text.encode()))
    target.chmod(0o600)
    return CookieStatus(platform, True, target.stat().st_mtime, entries, earliest)


def load_cookies(platform: str) -> str | None:
    target = _path(platform)
    if not target.exists():
        return None
    try:
        return _fernet().decrypt(target.read_bytes()).decode()
    except InvalidToken:
        # SECRET_KEY 가 바뀌면 복호화가 불가능하다 — 재등록을 요구한다.
        return None


def delete_cookies(platform: str) -> None:
    _path(platform).unlink(missing_ok=True)


def status(platform: str) -> CookieStatus:
    text = load_cookies(platform)
    if text is None:
        return CookieStatus(platform, False)
    try:
        entries, earliest = _validate(text)
    except ArchGrabError:
        return CookieStatus(platform, False)
    return CookieStatus(platform, True, _path(platform).stat().st_mtime, entries, earliest)


def all_status() -> list[CookieStatus]:
    return [status(p) for p in SUPPORTED]


@contextmanager
def cookie_file(platform: str) -> Iterator[Path | None]:
    """복호화한 쿠키를 0600 임시 파일로 잠깐 내놨다가 반드시 지운다.

    엔진(gallery-dl·yt-dlp)이 파일 경로만 받기 때문에 디스크를 거칠 수밖에 없다.
    /tmp 가 아니라 secrets_dir 안에 만들고, 예외가 나도 finally 에서 지운다.
    """
    text = load_cookies(platform)
    if text is None:
        yield None
        return

    settings = get_settings()
    settings.ensure_dirs()
    handle = tempfile.NamedTemporaryFile(
        mode="w", suffix=".cookies.txt", dir=settings.secrets_dir, delete=False, encoding="utf-8"
    )
    path = Path(handle.name)
    try:
        path.chmod(0o600)
        handle.write(text)
        handle.close()
        yield path
    finally:
        handle.close()
        path.unlink(missing_ok=True)
