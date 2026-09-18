"""작업 디렉터리, 안전한 파일명, 서명 파일 토큰."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from itsdangerous import BadSignature, SignatureExpired

from app.config import get_settings
from app.core.errors import ErrorCode, ArchGrabError
from app.core.security import get_serializer

_SALT = "file"
_UNSAFE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_SPACES = re.compile(r"\s+")


def safe_name(name: str, *, fallback: str = "file", max_length: int = 120) -> str:
    """경로 탈출과 OS 예약 문자를 제거한 파일명."""
    text = unicodedata.normalize("NFC", name).strip()
    text = _UNSAFE.sub("_", text)
    text = _SPACES.sub(" ", text).strip(" ._")
    text = text.replace("..", "_")
    if not text:
        return fallback
    stem, dot, ext = text.rpartition(".")
    if dot and len(ext) <= 5:
        return f"{stem[: max_length - len(ext) - 1]}.{ext}"
    return text[:max_length]


def job_dir(job_id: str) -> Path:
    """작업별 디렉터리. job_id 는 uuid4 hex 라 경로 탈출 위험이 없지만 한 번 더 검사한다."""
    if not re.fullmatch(r"[0-9a-f]{32}", job_id):
        raise ArchGrabError(ErrorCode.NOT_FOUND, detail="잘못된 작업 ID")
    settings = get_settings()
    path = settings.data_dir / job_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def make_token(job_id: str, name: str) -> str:
    return get_serializer(_SALT).dumps({"job": job_id, "name": name})


def resolve_token(token: str) -> Path:
    """토큰 → 실제 파일 경로. 위조·만료·경로 탈출을 모두 여기서 막는다."""
    settings = get_settings()
    try:
        payload = get_serializer(_SALT).loads(token, max_age=settings.file_ttl_seconds)
    except SignatureExpired as exc:
        raise ArchGrabError(
            ErrorCode.NOT_FOUND, "다운로드 링크가 만료되었습니다. 다시 받아주세요."
        ) from exc
    except (BadSignature, RuntimeError) as exc:
        raise ArchGrabError(ErrorCode.NOT_FOUND, detail="잘못된 토큰") from exc

    if not isinstance(payload, dict):
        raise ArchGrabError(ErrorCode.NOT_FOUND, detail="잘못된 토큰")

    base = job_dir(str(payload.get("job", "")))
    target = (base / safe_name(str(payload.get("name", "")))).resolve()
    if not target.is_relative_to(base.resolve()) or not target.is_file():
        raise ArchGrabError(ErrorCode.NOT_FOUND, "파일이 없습니다. 보관 기간이 지났을 수 있습니다.")
    return target


_THUMB_SALT = "thumb"
_THUMB_MAX_AGE = 3600


def make_thumb_token(url: str) -> str:
    """우리가 추출한 썸네일 주소만 프록시하도록 서명해둔다 (오픈 프록시 방지)."""
    return get_serializer(_THUMB_SALT).dumps(url)


def resolve_thumb_token(token: str) -> str:
    try:
        url = get_serializer(_THUMB_SALT).loads(token, max_age=_THUMB_MAX_AGE)
    except (BadSignature, SignatureExpired, RuntimeError) as exc:
        raise ArchGrabError(ErrorCode.NOT_FOUND, detail="잘못된 썸네일 토큰") from exc
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        raise ArchGrabError(ErrorCode.NOT_FOUND, detail="잘못된 썸네일 토큰")
    return url
