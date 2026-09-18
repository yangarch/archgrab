from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

TEST_PASSWORD = "test-password"


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """설정을 tmp_path 로 격리한다. 환경변수가 .env 보다 우선하므로 개발용 값과 섞이지 않는다."""
    from app.config import get_settings
    from app.core.security import hash_password

    monkeypatch.setenv("ARCHGRAB_SECRET_KEY", "test-secret-key-for-tests")
    monkeypatch.setenv("ARCHGRAB_PASSWORD_HASH", hash_password(TEST_PASSWORD))
    monkeypatch.setenv("ARCHGRAB_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ARCHGRAB_SECRETS_DIR", str(tmp_path / "secrets"))
    monkeypatch.setenv("ARCHGRAB_DB_PATH", str(tmp_path / "data" / "test.db"))
    monkeypatch.setenv("ARCHGRAB_STATIC_DIR", str(tmp_path / "static"))

    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()
