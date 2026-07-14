import os

import pytest
from pydantic import ValidationError

from app.config import _REPO_ROOT, Settings  # noqa: F401


def test_default_settings(monkeypatch):
    # Explicitly clear environment variables that pydantic-settings would pick up,
    # so the test is not sensitive to whatever APP_ENV the CI runner sets.
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    s = Settings()
    assert s.app_name == "ExpertSeat API"
    assert s.app_env == "development"


def test_default_database_url_password(monkeypatch):
    # Default password must match docker-compose.yml POSTGRES_PASSWORD.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    s = Settings()
    assert "expertseat_dev" in s.database_url, (
        "Default DATABASE_URL password must be 'expertseat_dev' to match docker-compose.yml"
    )


def test_explicit_env_override(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    s = Settings()
    assert s.app_env == "test"


def test_invalid_env():
    with pytest.raises(ValidationError):
        Settings(app_env="invalid")


def test_default_timeout_fields(monkeypatch):
    monkeypatch.delenv("DB_CONNECT_TIMEOUT", raising=False)
    monkeypatch.delenv("REDIS_CONNECT_TIMEOUT", raising=False)
    monkeypatch.delenv("REDIS_SOCKET_TIMEOUT", raising=False)
    s = Settings()
    assert s.db_connect_timeout > 0
    assert s.redis_connect_timeout > 0
    assert s.redis_socket_timeout > 0


def test_env_file_path_is_cwd_independent():
    """The .env file path must resolve to the repo root regardless of CWD.

    This test verifies that config.py uses an absolute path (derived from __file__)
    rather than a relative path that would break when run from a different directory.
    """
    # _REPO_ROOT is the Path object computed at import time from __file__.
    assert _REPO_ROOT.is_absolute(), "_REPO_ROOT must be an absolute path"
    # The repo root must contain a .env.example (committed sentinel file).
    assert (_REPO_ROOT / ".env.example").exists(), (
        f"_REPO_ROOT ({_REPO_ROOT}) does not point to the repository root "
        "(expected to find .env.example there)"
    )


def test_settings_cwd_independent(tmp_path, monkeypatch):
    """Settings() must not change behaviour when CWD changes."""
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)

    # Change CWD to a temp directory with no .env file.
    original_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        s = Settings()
        assert s.app_env == "development"
    finally:
        os.chdir(original_cwd)


# ── Production dotenv tests ───────────────────────────────────────────────────
#
# These tests use a temporary .env file containing a unique sentinel DATABASE_URL.
# They verify that production mode skips dotenv regardless of HOW production is
# selected (environment variable or __init__ kwarg), and that development loads it.


def test_development_loads_dotenv_sentinel(tmp_path, monkeypatch):
    """Development Settings() must load DATABASE_URL from dotenv."""
    sentinel_env = tmp_path / ".env"
    sentinel_env.write_text("DATABASE_URL=postgresql://sentinel:s@localhost/from_dotenv\n")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("APP_ENV", "development")
    s = Settings(_env_file=str(sentinel_env))  # type: ignore[call-arg]
    assert "from_dotenv" in s.database_url, (
        f"Development must load DATABASE_URL from dotenv, got: {s.database_url!r}"
    )


def test_test_mode_may_load_dotenv_sentinel(tmp_path, monkeypatch):
    """Test-mode Settings() must load DATABASE_URL from dotenv."""
    sentinel_env = tmp_path / ".env"
    sentinel_env.write_text("DATABASE_URL=postgresql://sentinel:s@localhost/from_dotenv\n")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("APP_ENV", "test")
    s = Settings(_env_file=str(sentinel_env))  # type: ignore[call-arg]
    assert "from_dotenv" in s.database_url, (
        f"Test mode must load DATABASE_URL from dotenv, got: {s.database_url!r}"
    )


def test_env_selected_production_does_not_load_dotenv(tmp_path, monkeypatch):
    """APP_ENV=production in the OS environment must skip the dotenv file."""
    sentinel_env = tmp_path / ".env"
    sentinel_env.write_text("DATABASE_URL=postgresql://sentinel:s@localhost/from_dotenv\n")
    # Provide explicit values so production validation does not fail.
    monkeypatch.setenv("DATABASE_URL", "postgresql://prod:x@prod-host:5432/proddb")
    monkeypatch.setenv("REDIS_URL", "redis://prod-redis:6379/0")
    monkeypatch.setenv("SECRET_KEY", "production-secret-key-that-is-long-enough-00")
    monkeypatch.setenv("RATE_LIMIT_SECRET", "production-rate-limit-secret-long-enough-xx")
    monkeypatch.setenv("APP_ENV", "production")
    s = Settings(_env_file=str(sentinel_env))  # type: ignore[call-arg]
    assert "from_dotenv" not in s.database_url, (
        f"Environment-selected production must not load dotenv, got: {s.database_url!r}"
    )
    assert "prod-host" in s.database_url


def test_init_selected_production_does_not_load_dotenv(tmp_path, monkeypatch):
    """Settings(app_env='production') must skip the dotenv file.

    This verifies that init-kwarg production selection (not just OS env) triggers
    the dotenv bypass. The check happens in settings_customise_sources before
    any values are applied.
    """
    sentinel_env = tmp_path / ".env"
    sentinel_env.write_text("DATABASE_URL=postgresql://sentinel:s@localhost/from_dotenv\n")
    monkeypatch.delenv("APP_ENV", raising=False)
    # Provide explicit values so production validation does not fail.
    monkeypatch.setenv("DATABASE_URL", "postgresql://prod:x@prod-host:5432/proddb")
    monkeypatch.setenv("REDIS_URL", "redis://prod-redis:6379/0")
    monkeypatch.setenv("SECRET_KEY", "production-secret-key-that-is-long-enough-00")
    monkeypatch.setenv("RATE_LIMIT_SECRET", "production-rate-limit-secret-long-enough-xx")
    s = Settings(app_env="production", _env_file=str(sentinel_env))  # type: ignore[call-arg]
    assert "from_dotenv" not in s.database_url, (
        f"Init-selected production must not load dotenv, got: {s.database_url!r}"
    )
    assert "prod-host" in s.database_url


def test_explicit_env_var_overrides_dotenv_in_development(tmp_path, monkeypatch):
    """An explicit environment variable must win over dotenv in development."""
    sentinel_env = tmp_path / ".env"
    sentinel_env.write_text("DATABASE_URL=postgresql://sentinel:s@localhost/from_dotenv\n")
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DATABASE_URL", "postgresql://explicit:x@localhost/from_env")
    s = Settings(_env_file=str(sentinel_env))  # type: ignore[call-arg]
    assert "from_env" in s.database_url, (
        f"Explicit env var must win over dotenv, got: {s.database_url!r}"
    )


def test_production_rejects_development_database_url(monkeypatch):
    """Production must fail validation if DATABASE_URL is the development default.

    This prevents accidental use of development credentials in production when
    DATABASE_URL is simply not set in the environment.
    """
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SECRET_KEY", "production-secret-key-that-is-long-enough-00")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    with pytest.raises(ValidationError, match="DATABASE_URL must be explicitly set in production"):
        Settings()


def test_production_rejects_development_redis_url(monkeypatch):
    """Production must fail validation if REDIS_URL is the development default."""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SECRET_KEY", "production-secret-key-that-is-long-enough-00")
    monkeypatch.setenv("DATABASE_URL", "postgresql://prod:x@prod-host:5432/proddb")
    monkeypatch.delenv("REDIS_URL", raising=False)
    with pytest.raises(ValidationError, match="REDIS_URL must be explicitly set in production"):
        Settings()


# ── SECRET_KEY validation ─────────────────────────────────────────────────────


def test_secret_key_too_short_raises(monkeypatch):
    """Settings must fail validation if SECRET_KEY is shorter than 32 characters."""
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.setenv("SECRET_KEY", "short")
    with pytest.raises(ValidationError, match="SECRET_KEY must be at least 32 characters"):
        Settings()


def test_secret_key_exactly_32_chars_is_accepted(monkeypatch):
    """A 32-character SECRET_KEY must pass validation."""
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.setenv("SECRET_KEY", "a" * 32)
    s = Settings()
    assert len(s.secret_key) == 32


def test_secret_key_empty_raises(monkeypatch):
    """An empty SECRET_KEY must fail validation."""
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.setenv("SECRET_KEY", "")
    with pytest.raises(ValidationError, match="SECRET_KEY must be at least 32 characters"):
        Settings()


def test_production_rejects_development_secret_key(monkeypatch):
    """Production must fail validation if SECRET_KEY is the development default."""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql://prod:x@prod-host:5432/proddb")
    monkeypatch.setenv("REDIS_URL", "redis://prod-redis:6379/0")
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(ValidationError, match="SECRET_KEY must be explicitly set in production"):
        Settings()
