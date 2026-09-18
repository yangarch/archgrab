#!/usr/bin/env python3
"""PreToolUse(Bash) 가드 — 비밀값·개인정보가 밖으로 나가는 명령을 막는다.

깃 훅(.githooks/scan.py)이 커밋·푸시를 막지만 세 가지 구멍이 남는다:
  1. `--no-verify` 로 깃 훅 자체를 건너뛰는 경우
  2. 깃을 거치지 않는 전송 (curl, scp, gh gist, rclone …)
  3. 비밀 파일을 터미널에 출력해 대화 기록(=API 로 전송됨)에 남기는 경우
이 훅이 그 셋을 담당한다.

판정: deny = 실행 자체를 막는다 / ask = 사용자에게 물어본다.
stdin 으로 {"tool_input": {"command": "..."}} 를 받는다.
"""

from __future__ import annotations

import json
import re
import sys

# 보호 대상 경로. .env.example 과 .gitkeep 은 제외한다.
SENSITIVE = re.compile(
    r"""(
          \.env\b(?!\.example)          # .env, .env.local …
        | \.dev-password
        | (^|[\s'"/=])secrets/          # secrets/ 디렉터리
        | (^|[\s'"/=])data/             # 내려받은 미디어·작업 DB
        | \.cookies\.(txt|enc)
        | (^|/)cookies\.txt
        | archgrab\.db
    )""",
    re.X,
)
GITKEEP_ONLY = re.compile(r"(secrets|data)/\.gitkeep\b")

# 밖으로 내보내는 도구
EGRESS = re.compile(
    r"\b(curl|wget|scp|sftp|rsync|nc|ncat|socat|ssh|gh|http|https|httpie"
    r"|aws|gsutil|s3cmd|rclone|croc|magic-wormhole|wormhole|pastebinit)\b"
)

# 내용을 터미널에 쏟는 도구 (대화 기록에 남는다)
READERS = re.compile(r"\b(cat|bat|less|more|head|tail|strings|xxd|od|base64|tee|pbcopy)\b")


def _decide(command: str) -> tuple[str, str] | None:
    """(판정, 이유) 또는 None(통과)."""
    text = command

    # 스캐너 우회 환경변수
    if "ARCHGRAB_ALLOW_SECRET" in text:
        return "deny", (
            "비밀값 스캐너를 무력화하는 환경변수입니다. 정말 필요하면 터미널에서 직접 실행하세요."
        )

    # 깃 훅 우회
    if re.search(r"\bgit\b", text) and re.search(r"--no-verify|(?<![\w-])-n(?![\w-])", text):
        if re.search(r"\b(commit|push)\b", text):
            return "deny", (
                "--no-verify 는 비밀값 검사(.githooks/pre-commit)를 건너뜁니다. "
                "검사를 통과하도록 내용을 고치세요."
            )

    # 훅 경로 변경 = 검사 비활성화
    if re.search(r"git\s+config.*core\.hooksPath", text) and "--get" not in text:
        return "deny", "core.hooksPath 를 바꾸면 비밀값 검사가 비활성화됩니다."

    # .githooks 삭제·비활성화
    if re.search(r"\brm\b.*\.githooks|chmod\s+-x.*\.githooks", text):
        return "deny", "비밀값 검사 훅을 제거하는 명령입니다."

    if not SENSITIVE.search(text) or (
        GITKEEP_ONLY.search(text) and not SENSITIVE.sub("", GITKEEP_ONLY.sub("", text)).strip()
    ):
        return None

    # 여기부터는 민감 경로가 명령에 들어 있다
    if EGRESS.search(text):
        return "deny", (
            "비밀값·개인정보가 담긴 경로를 외부 전송 도구와 함께 쓰고 있습니다. "
            "업로드 대상에서 제외하세요."
        )

    if re.search(r"git\s+add\b", text) and re.search(r"(?<![\w-])(-f|--force)(?![\w-])", text):
        return "deny", "민감 경로를 강제로 스테이징하려는 명령입니다 (.gitignore 를 무시)."

    if READERS.search(text):
        return "ask", (
            "비밀 파일 내용을 출력하려 합니다. 출력은 대화 기록에 남아 외부로 전송됩니다."
        )

    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0                      # 입력을 못 읽으면 통과시킨다 (작업을 막지 않는다)

    command = str((payload.get("tool_input") or {}).get("command") or "")
    if not command:
        return 0

    verdict = _decide(command)
    if verdict is None:
        return 0

    decision, reason = verdict
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": decision,
                    "permissionDecisionReason": f"[archgrab 가드] {reason}",
                }
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
