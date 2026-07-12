from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # App
    app_name: str = "ExpertSeat API"
    app_env: str = "development"
    debug: bool = False

    # Database
    database_url: str = "postgresql://expertseat:expertseat@localhost:5432/expertseat"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # API
    api_v1_prefix: str = "/api/v1"
    cors_allowed_origins: list[str] = ["http://localhost:3000"]

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
