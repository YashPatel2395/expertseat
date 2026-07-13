import os
from pathlib import Path

from pydantic import field_validator, model_validator
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

    # Auth — SECRET_KEY must be overridden in production.
    # The default is rejected by the production model validator.
    # Generate with: python3 -c "import secrets; print(secrets.token_hex(32))"
    secret_key: str = "dev-only-do-not-use-in-production-change-me-00"

    # Token lifetimes (seconds)
    access_token_ttl: int = 600  # 10 minutes
    refresh_token_ttl: int = 1_209_600  # 14 days

    # Rate limiting (fixed-window)
    rate_limit_auth_max: int = 10  # max attempts per window
    rate_limit_auth_window: int = 60  # window in seconds

    # Email (SMTP — dev default matches Mailpit in docker-compose.yml)
    mailpit_host: str = "localhost"
    mailpit_port: int = 1025
    email_from: str = "noreply@expertseat.local"

    @field_validator("app_env")
    @classmethod
    def validate_env(cls, v: str) -> str:
        allowed = {"development", "test", "production"}
        if v not in allowed:
            raise ValueError(f"app_env must be one of {allowed}")
        return v

    @field_validator("secret_key")
    @classmethod
    def validate_secret_key(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError(
                "SECRET_KEY must be at least 32 characters. "
                'Generate one with: python3 -c "import secrets; print(secrets.token_hex(32))"'
            )
        return v

    @model_validator(mode="after")
    def validate_production_secrets(self) -> "Settings":
        """In production, development credential defaults must not be used.

        This guard ensures that a misconfigured production process fails loudly
        rather than connecting to development infrastructure.
        """
        if self.app_env == "production":
            _dev_db = "postgresql://expertseat:expertseat_dev@localhost:5432/expertseat"
            _dev_redis = "redis://localhost:6379/0"
            _dev_key = "dev-only-do-not-use-in-production-change-me-00"
            if self.database_url == _dev_db:
                raise ValueError(
                    "DATABASE_URL must be explicitly set in production; "
                    "the development default cannot be used"
                )
            if self.redis_url == _dev_redis:
                raise ValueError(
                    "REDIS_URL must be explicitly set in production; "
                    "the development default cannot be used"
                )
            if self.secret_key == _dev_key:
                raise ValueError(
                    "SECRET_KEY must be explicitly set in production; "
                    "the development default cannot be used"
                )
        return self

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        # Skip dotenv when production is selected via OS environment OR via init kwarg.
        # Checking init_settings() detects Settings(app_env="production") at construction
        # time, before dotenv values are applied.
        is_production = os.getenv("APP_ENV") == "production" or (
            init_settings().get("app_env") == "production"
        )
        if is_production:
            return (init_settings, env_settings, file_secret_settings)
        return (init_settings, env_settings, dotenv_settings, file_secret_settings)


def get_settings() -> Settings:
    return Settings()


settings = get_settings()
