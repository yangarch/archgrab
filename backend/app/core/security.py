"""비밀번호 해시, 서명 토큰, 로그 마스킹."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re

from itsdangerous import URLSafeTimedSerializer

from app.config import get_settings

_SCRYPT_N = 2 ** 15
_SCRYPT_R = 8
_SCRYPT_P = 1
_DKLEN = 32
# 128 * n * r = 32MB 가 필요한데 OpenSSL 기본 상한이 정확히 32MB 라 넉넉히 올려준다.
_MAXMEM = 96 * 1024 * 1024


def hash_password(password: str) -> str:
    """scrypt$n$r$p$salt$hash — stdlib 만으로 충분하고 네이티브 의존성이 없다."""
    salt = os.urandom(16)
    digest = hashlib.scrypt(
        password.encode(),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_DKLEN,
        maxmem=_MAXMEM,
    )
    b64 = lambda raw: base64.b64encode(raw).decode()  # noqa: E731
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${b64(salt)}${b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_b64, hash_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = base64.b64decode(hash_b64)
        actual = hashlib.scrypt(
            password.encode(),
            salt=base64.b64decode(salt_b64),
            n=int(n), r=int(r), p=int(p),
            dklen=len(expected),
            maxmem=_MAXMEM,
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def get_serializer(salt: str) -> URLSafeTimedSerializer:
    """용도별 salt 로 분리해, 세션 토큰을 파일 토큰으로 재사용할 수 없게 한다."""
    secret = get_settings().secret_key
    if not secret:
        raise RuntimeError("ARCHGRAB_SECRET_KEY 가 설정되지 않았습니다 (.env 확인)")
    return URLSafeTimedSerializer(secret, salt=f"archgrab.{salt}")


# 쿠키 파일·엔진 로그가 그대로 찍히는 사고를 막는다.
_SENSITIVE = re.compile(
    r"(sessionid|csrftoken|ds_user_id|auth_token|ct0|mid|ig_did|SAPISID|__Secure-[A-Za-z0-9_-]+)"
    r"\s*[=:]\s*([^\s;,'\"]+)",
    re.I,
)


def mask_secrets(text: str) -> str:
    return _SENSITIVE.sub(lambda m: f"{m.group(1)}=***", text)
