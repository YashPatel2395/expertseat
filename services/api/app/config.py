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
    refresh_family_ttl: int = 1_209_600  # 14 days — absolute session family lifetime
    password_reset_ttl: int = 1_800  # 30 minutes

    # Rate limiting (fixed-window)
    rate_limit_auth_max: int = 10  # max attempts per window
    rate_limit_auth_window: int = 60  # window in seconds
    # Invitation-specific rate limits (separate from auth limits)
    rate_limit_invitation_max: int = 10  # max invitation actions per window
    rate_limit_invitation_window: int = 3600  # 1-hour window for invitations
    # Dedicated HMAC secret for rate-limit key derivation.
    # Required in production; must be at least 32 chars and different from SECRET_KEY.
    rate_limit_secret: str = ""

    # Outbox payload encryption (AES-256-GCM via cryptography library).
    # Hex-encoded 32-byte (256-bit) key — separate from SECRET_KEY and RATE_LIMIT_SECRET.
    # Generate: python3 -c "import secrets; print(secrets.token_hex(32))"
    # Required in production; must differ from SECRET_KEY.
    outbox_encryption_key: str = ""
    # Keyring format: 'v1:<hex>,v2:<hex>' — preferred over outbox_encryption_key.
    outbox_encryption_keys: str = ""
    # Identifies the active key slot for key rotation.  Records store this
    # so the worker can select the correct key on decryption.
    outbox_active_key_id: str = "v1"
    # Maximum delivery attempts before a row is moved to 'dead' status.
    outbox_max_attempts: int = 3
    # Lock expiry in seconds — processing locks held longer than this are
    # reclaimed by subsequent workers.
    outbox_lock_expiry_seconds: int = 300  # 5 minutes

    # Versioned terms and privacy notice
    current_terms_version: str = "2026-07-01"
    supported_terms_versions: list[str] = ["2026-07-01"]
    current_privacy_version: str = "2026-07-01"
    supported_privacy_versions: list[str] = ["2026-07-01"]

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
            if not self.rate_limit_secret:
                raise ValueError(
                    "RATE_LIMIT_SECRET must be set in production; "
                    "it must be at least 32 characters and different from SECRET_KEY"
                )
            if len(self.rate_limit_secret) < 32:
                raise ValueError("RATE_LIMIT_SECRET must be at least 32 characters")
            if self.rate_limit_secret == self.secret_key:
                raise ValueError("RATE_LIMIT_SECRET must be different from SECRET_KEY")
            # Require at least one outbox key in production
            if not self.outbox_encryption_keys and not self.outbox_encryption_key:
                raise ValueError(
                    "OUTBOX_ENCRYPTION_KEYS (or OUTBOX_ENCRYPTION_KEY) must be set in production"
                )
            # Validate whichever is set
            if self.outbox_encryption_keys:
                for entry in self.outbox_encryption_keys.split(","):
                    kid_part, _, hex_part = entry.strip().partition(":")
                    if not kid_part or not hex_part:
                        raise ValueError(
                            f"OUTBOX_ENCRYPTION_KEYS entry {entry!r} must be 'kid:hex'"
                        )
                    try:
                        key_bytes = bytes.fromhex(hex_part)
                    except ValueError as exc:
                        raise ValueError(
                            f"OUTBOX_ENCRYPTION_KEYS key '{kid_part}' is not valid hex"
                        ) from exc
                    if len(key_bytes) != 32:
                        raise ValueError(
                            f"OUTBOX_ENCRYPTION_KEYS key '{kid_part}' must be 32 bytes; "
                            f"got {len(key_bytes)}"
                        )
            elif self.outbox_encryption_key:
                try:
                    key_bytes = bytes.fromhex(self.outbox_encryption_key)
                except ValueError as exc:
                    raise ValueError("OUTBOX_ENCRYPTION_KEY must be a hex-encoded string") from exc
                if len(key_bytes) != 32:
                    raise ValueError(
                        "OUTBOX_ENCRYPTION_KEY must be exactly 32 bytes (64 hex characters)"
                    )
                if self.outbox_encryption_key == self.secret_key:
                    raise ValueError("OUTBOX_ENCRYPTION_KEY must be different from SECRET_KEY")
                if self.outbox_encryption_key == self.rate_limit_secret:
                    raise ValueError(
                        "OUTBOX_ENCRYPTION_KEY must be different from RATE_LIMIT_SECRET"
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
