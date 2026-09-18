"""비밀번호 해시와 SECRET_KEY 를 만들어 .env 에 붙여넣을 형태로 출력한다.

    python -m app.tools.hashpw
"""

from __future__ import annotations

import getpass
import secrets
import sys

from app.core.security import hash_password


def main() -> int:
    password = getpass.getpass("새 비밀번호: ")
    if not password:
        print("비밀번호가 비어 있습니다.", file=sys.stderr)
        return 1
    if password != getpass.getpass("확인: "):
        print("두 입력이 다릅니다.", file=sys.stderr)
        return 1

    print("\n# .env 에 아래 두 줄을 넣어주세요")
    print(f"ARCHGRAB_SECRET_KEY={secrets.token_urlsafe(48)}")
    print(f"ARCHGRAB_PASSWORD_HASH={hash_password(password)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
