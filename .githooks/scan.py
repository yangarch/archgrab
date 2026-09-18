#!/usr/bin/env python3
"""커밋·푸시 대상에서 개인정보와 비밀값을 찾아낸다.

경로 규칙과 내용 규칙을 함께 본다. 경로만 막으면 파일 이름을 바꿔 우회되고,
내용만 보면 바이너리·인코딩된 값을 놓친다.

오탐이 나면 규칙을 고치는 게 원칙이다. 급할 때만:
    ARCHGRAB_ALLOW_SECRET=1 git commit ...
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass

# ---- 경로 규칙 ------------------------------------------------------------
# 무엇이 들었든 이 경로는 커밋 대상이 아니다.
BLOCKED_PATHS: tuple[tuple[str, str], ...] = (
    (r"^\.env$", "실제 SECRET_KEY·비밀번호 해시가 담긴 파일"),
    (r"^\.env\.(?!example$)", ".env 파생 파일 (예: .env.local, .env.prod)"),
    (r"^\.dev-password$", "평문 비밀번호"),
    (r"^secrets/(?!\.gitkeep$)", "쿠키 저장소 — 인스타/X 세션"),
    (r"^data/(?!\.gitkeep$)", "내려받은 미디어와 작업 DB"),
    (r"\.cookies\.(txt|enc)$", "쿠키 파일"),
    (r"(^|/)cookies\.txt$", "쿠키 파일"),
    (r"\.(sqlite3?|db)(-wal|-shm)?$", "데이터베이스 파일"),
    (r"(^|/)\.DS_Store$", "OS 메타데이터"),
)

# ---- 내용 규칙 ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Rule:
    name: str
    pattern: re.Pattern[str]
    why: str
    # 자리표시자·템플릿을 실제 비밀값과 구분해야 할 때만 쓴다
    needs_real_value: bool = False


_PLACEHOLDER = re.compile(
    r"^(\{|<|\$|%|\*|your[-_]|changeme|replace|xxx+|dummy|sample|example)", re.I
)
_SECRET_SHAPE = re.compile(r"^[A-Za-z0-9+/=_.$-]+$")


def looks_like_real_secret(value: str) -> bool:
    """자리표시자가 아니고 실제 토큰처럼 생겼는지.

    `.env.example` 의 빈 값과 `hashpw.py` 의 f-string 자리표시자를 걸러내려고 있다.
    이게 없으면 스캐너가 매 커밋마다 오탐을 내고, 결국 아무도 신뢰하지 않게 된다.
    """
    value = value.strip().strip("\"'")
    if len(value) < 16:
        return False
    if _PLACEHOLDER.search(value):
        return False
    if "{" in value or "<" in value:      # f-string / 템플릿
        return False
    return bool(_SECRET_SHAPE.match(value))


CONTENT_RULES: tuple[Rule, ...] = (
    Rule(
        "SECRET_KEY",
        # 값은 같은 줄에서만 찾는다. \s 를 쓰면 개행을 넘어 다음 줄을 값으로 문다.
        re.compile(r"ARCHGRAB_SECRET_KEY[ \t]*=[ \t]*(?P<value>[^\s#]+)"),
        "세션 위조와 쿠키 복호화가 동시에 가능해진다",
        needs_real_value=True,
    ),
    Rule(
        "PASSWORD_HASH",
        re.compile(r"ARCHGRAB_PASSWORD_HASH[ \t]*=[ \t]*(?P<value>[^\s#]+)"),
        "오프라인 대입 공격의 대상이 된다",
        needs_real_value=True,
    ),
    Rule(
        "scrypt 해시",
        re.compile(r"(?P<value>scrypt\$\d+\$\d+\$\d+\$[A-Za-z0-9+/=]{16,})"),
        "비밀번호 해시 형식",
    ),
    Rule(
        "세션 쿠키값",
        re.compile(
            r"(sessionid|csrftoken|ds_user_id|auth_token|ct0|ig_did|SAPISID)"
            r"[ \t=:]+(?P<value>[A-Za-z0-9%_\-.:]{12,})"
        ),
        "계정에 그대로 접근할 수 있는 값",
    ),
    Rule(
        "개인 키",
        re.compile(r"(?P<value>-----BEGIN [A-Z ]*PRIVATE KEY-----)"),
        "비밀 키",
    ),
    Rule(
        "홈 디렉터리 경로",
        re.compile(r"(?P<value>/(?:Users|home)/(?!runner\b|user\b)[a-z][a-z0-9._-]{2,}/)"),
        "OS 사용자명이 드러난다",
    ),
    Rule(
        "이메일 주소",
        re.compile(
            r"(?<![A-Za-z0-9._%+-])(?P<value>[A-Za-z0-9._%+-]+@"
            r"(?!example\.(com|org)|scontent\.example|anthropic\.com)"
            r"[A-Za-z0-9.-]+\.[A-Za-z]{2,})"
        ),
        "개인정보",
    ),
)

# 스캐너 자신은 규칙 문자열 때문에 항상 걸린다.
SELF_EXEMPT = {".githooks/scan.py"}


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, check=True
    ).stdout


def staged_paths() -> list[str]:
    output = _git("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z")
    return [p for p in output.split("\0") if p]


def paths_in_range(base: str, head: str) -> list[str]:
    output = _git("diff", "--name-only", "--diff-filter=ACMR", "-z", base, head)
    return [p for p in output.split("\0") if p]


def blob(path: str, ref: str = "") -> str | None:
    """스테이징된(또는 주어진 커밋의) 내용. 바이너리면 None."""
    try:
        raw = subprocess.run(
            ["git", "show", f"{ref}:{path}"], capture_output=True, check=True
        ).stdout
    except subprocess.CalledProcessError:
        return None
    if b"\0" in raw[:8000]:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def scan(paths: list[str], ref: str = "") -> list[str]:
    problems: list[str] = []

    for path in paths:
        for pattern, why in BLOCKED_PATHS:
            if re.search(pattern, path):
                problems.append(f"  [경로] {path}\n         → {why}")
                break
        else:
            if path in SELF_EXEMPT:
                continue
            text = blob(path, ref)
            if text is None:
                continue
            for rule in CONTENT_RULES:
                for match in rule.pattern.finditer(text):
                    value = match.groupdict().get("value") or match.group(0)
                    if rule.needs_real_value and not looks_like_real_secret(value):
                        continue
                    line = text[: match.start()].count("\n") + 1
                    excerpt = value if len(value) <= 24 else value[:24] + "…"
                    problems.append(
                        f"  [내용] {path}:{line}  {rule.name}: {excerpt}\n"
                        f"         → {rule.why}"
                    )
                    break
                else:
                    continue
                break

    return problems


def report(problems: list[str], action: str) -> int:
    if not problems:
        return 0
    print(f"\n\033[31m✗ {action} 차단 — 올려서는 안 되는 내용이 있습니다\033[0m\n")
    print("\n".join(problems))
    print(
        "\n수정 방법:"
        "\n  · 실수로 추가했다면:  git restore --staged <경로>"
        "\n  · 이미 추적 중이라면:  git rm --cached <경로>  (파일은 남습니다)"
        "\n  · 규칙이 틀렸다면 .githooks/scan.py 를 고치세요"
        f"\n  · 정말 의도한 것이라면:  ARCHGRAB_ALLOW_SECRET=1 git {action}\n"
    )
    return 1


def main(argv: list[str]) -> int:
    if os.environ.get("ARCHGRAB_ALLOW_SECRET"):
        print("⚠ ARCHGRAB_ALLOW_SECRET 이 설정되어 검사를 건너뜁니다")
        return 0

    mode = argv[1] if len(argv) > 1 else "commit"

    if mode == "push":
        # stdin: <local ref> <local sha> <remote ref> <remote sha>
        problems: list[str] = []
        for line in sys.stdin:
            fields = line.split()
            if len(fields) != 4:
                continue
            local_sha, remote_sha = fields[1], fields[3]
            if local_sha == "0" * 40:
                continue
            base = remote_sha if remote_sha != "0" * 40 else _git(
                "rev-list", "--max-parents=0", local_sha
            ).split()[0]
            problems += scan(paths_in_range(base, local_sha), ref=local_sha)
        return report(problems, "push")

    return report(scan(staged_paths()), "commit")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
