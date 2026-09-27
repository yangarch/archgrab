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
    """scrypt:n:r:p:salt:hash — stdlib 만으로 충분하고 네이티브 의존성이 없다.

    구분자가 `:` 인 이유: 예전엔 PHC 관례대로 `$` 를 썼는데, docker compose 의
    `env_file` 은 값 안의 `$이름` 을 셸 변수로 해석해 빈 문자열로 바꿔버린다.
    그래서 해시가 6필드에서 4필드로 잘린 채 컨테이너에 도착하고, 올바른
    비밀번호도 항상 거부됐다(compose 경고: 'The "..." variable is not set').
    base64 에는 `:` 가 나오지 않으므로 안전한 구분자다.
    """
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
    return f"scrypt:{_SCRYPT_N}:{_SCRYPT_R}:{_SCRYPT_P}:{b64(salt)}:{b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    # `:` 가 현재 형식, `$` 는 예전 형식 — 이미 발급된 해시가 계속 동작해야 한다.
    separator = ":" if ":" in stored else "$"
    try:
        scheme, n, r, p, salt_b64, hash_b64 = stored.split(separator)
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
