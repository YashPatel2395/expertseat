from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve the .env file relative to the repository root, not the process CWD.
# This file lives at services/api/app/config.py.
# Parent chain: app/ -> api/ -> services/ -> repo root.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App
    app_name: str = "ExpertSeat API"
    app_env: str = "development"
    debug: bool = False

    # Database — password matches infrastructure/docker-compose.yml POSTGRES_PASSWORD
    database_url: str = "postgresql://expertseat:expertseat_dev@localhost:5432/expertseat"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # API
    api_v1_prefix: str = "/api/v1"
    cors_allowed_origins: list[str] = ["http://localhost:3000"]

    # Health-check timeouts (seconds)
    db_connect_timeout: int = 5
    redis_connect_timeout: int = 2
    redis_socket_timeout: int = 2

    @field_validator("app_env")
    @classmethod
    def validate_env(cls, v: str) -> str:
        allowed = {"development", "test", "production"}
        if v not in allowed:
            raise ValueError(f"app_env must be one of {allowed}")
        return v


def get_settings() -> Settings:
    return Settings()


settings = get_settings()
