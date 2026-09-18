from __future__ import annotations

from fastapi import APIRouter, File, UploadFile

from app.auth import AuthRequired
from app.core import secrets_store
from app.core.errors import ErrorCode, ArchGrabError

router = APIRouter(prefix="/cookies", tags=["cookies"], dependencies=[AuthRequired])

MAX_BYTES = 512 * 1024


def _serialize(status: secrets_store.CookieStatus) -> dict[str, object]:
    return {
        "platform": status.platform,
        "present": status.present,
        "entries": status.entries,
        "updated_at": status.updated_at,
        "earliest_expiry": status.earliest_expiry,
        "expired": status.expired,
    }


@router.get("")
async def list_cookies() -> list[dict[str, object]]:
    return [_serialize(s) for s in secrets_store.all_status()]


@router.put("/{platform}")
async def put_cookies(platform: str, file: UploadFile = File(...)) -> dict[str, object]:
    raw = await file.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ArchGrabError(ErrorCode.UNSUPPORTED, "쿠키 파일이 너무 큽니다 (최대 512KB).")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ArchGrabError(ErrorCode.UNSUPPORTED, "텍스트 파일이 아닙니다.") from exc
    return _serialize(secrets_store.save_cookies(platform, text))


@router.delete("/{platform}")
async def remove_cookies(platform: str) -> dict[str, object]:
    secrets_store.delete_cookies(platform)
    return _serialize(secrets_store.status(platform))
