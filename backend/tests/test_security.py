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
