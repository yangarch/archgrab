from __future__ import annotations

from app.core.security import hash_password, mask_secrets, verify_password


def test_password_roundtrip() -> None:
    stored = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", stored)
    assert not verify_password("wrong", stored)


def test_verify_rejects_garbage_hash() -> None:
    assert not verify_password("x", "")
    assert not verify_password("x", "bcrypt$1$2$3$4$5")


def test_mask_secrets_hides_session_tokens() -> None:
    masked = mask_secrets("sessionid=12345abcdef; csrftoken=zzz")
    assert "12345abcdef" not in masked and "zzz" not in masked


class TestHashIsInterpolationSafe:
    """docker compose 의 env_file 은 값 안의 `$이름` 을 셸 변수로 해석한다.

    예전 형식(scrypt$n$r$p$salt$hash)은 base64 조각이 변수명으로 먹혀 6필드가
    4필드로 잘린 채 컨테이너에 도착했고, 올바른 비밀번호도 항상 거부됐다.
    """

    def test_new_hash_has_no_dollar_sign(self) -> None:
        assert "$" not in hash_password("whatever")

    def test_new_hash_uses_colon_separator(self) -> None:
        stored = hash_password("whatever")
        assert stored.startswith("scrypt:")
        assert len(stored.split(":")) == 6

    def test_legacy_dollar_format_still_verifies(self) -> None:
        """이미 .env 에 들어가 있는 예전 해시가 계속 동작해야 한다."""
        legacy = hash_password("my-password").replace(":", "$", 5)
        assert "$" in legacy
        assert verify_password("my-password", legacy)
        assert not verify_password("wrong", legacy)

    def test_truncated_hash_is_rejected_not_crashed(self) -> None:
        """보간으로 잘린 값이 들어와도 예외 없이 거부해야 한다."""
        truncated = "scrypt:32768:8:1::"
        assert not verify_password("anything", truncated)
