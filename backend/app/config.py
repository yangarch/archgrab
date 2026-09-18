from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent      # backend/
PROJECT_DIR = BASE_DIR.parent                           # repo root


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ARCHGRAB_",
        env_file=(PROJECT_DIR / ".env", BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 인증 — 둘 다 .env 로 주입한다. `make hashpw` 로 password_hash 생성.
    secret_key: str = ""
    password_hash: str = ""
    session_max_age: int = 30 * 24 * 3600
    cookie_secure: bool = False          # HTTPS 뒤에 두면 true
    login_max_attempts: int = 5          # 분당 IP 기준
    login_window: int = 60

    # 저장소
    data_dir: Path = PROJECT_DIR / "data"
    secrets_dir: Path = PROJECT_DIR / "secrets"
    static_dir: Path = BASE_DIR / "static"
    db_path: Path = PROJECT_DIR / "data" / "archgrab.db"

    # 동작
    file_ttl_seconds: int = 6 * 3600
    max_concurrent_downloads: int = 2
    resolve_cache_seconds: int = 600
    engine_timeout: int = 180
    proxy: str | None = None             # 예: socks5://127.0.0.1:1080

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.secrets_dir.mkdir(parents=True, exist_ok=True)
        self.secrets_dir.chmod(0o700)


@lru_cache
def get_settings() -> Settings:
    return Settings()
