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

    # 유튜브 봇 감지 우회용 player_client 목록 (쉼표 구분, 비우면 yt-dlp 기본값).
    # 데이터센터 IP 에서는 web 계열이 막히는 일이 잦다 — 집에서는 되는데 서버에서만
    # "Sign in to confirm you're not a bot" 이 나오는 게 그 증상이다.
    youtube_player_clients: str = ""
    # 봇 감지에 걸렸을 때 마지막으로 시도할 클라이언트.
    # 실측(2026-09): web·tv·ios·mweb·web_safari 는 전부 실패하고, 동작하는 건
    # visionos(1080p, 기본값)와 android 계열(360p)뿐이다. 즉 폴백은 화질을
    # 크게 떨어뜨리는 구제책이므로 쓰였다는 사실을 사용자에게 알려야 한다.
    youtube_fallback_clients: str = "android_vr,android"

    def client_list(self, raw: str) -> list[str]:
        return [c.strip() for c in raw.split(",") if c.strip()]

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.secrets_dir.mkdir(parents=True, exist_ok=True)
        self.secrets_dir.chmod(0o700)


@lru_cache
def get_settings() -> Settings:
    return Settings()
