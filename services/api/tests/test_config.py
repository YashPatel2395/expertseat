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


def test_production_does_not_load_dotenv(tmp_path, monkeypatch):
    """Production must skip the dotenv file even when a valid dotenv file is present.

    Creates a temporary .env file containing a unique sentinel DATABASE_URL value.
    When APP_ENV=production, Settings() must not load values from that file even
    when explicitly pointed at it via _env_file.

    Also proves that the same dotenv file IS loaded in development mode, and that
    an explicit environment variable takes priority over dotenv in development.
    """
    # Create a temp .env with a sentinel DATABASE_URL not in the real environment.
    sentinel_env = tmp_path / ".env"
    sentinel_env.write_text("DATABASE_URL=postgresql://sentinel:sentinel@localhost/from_dotenv\n")

    # Ensure DATABASE_URL is absent from the real environment so the only dotenv
    # source is our temp file.
    monkeypatch.delenv("DATABASE_URL", raising=False)

    # ── Production: dotenv must be silently skipped ──────────────────────────
    monkeypatch.setenv("APP_ENV", "production")
    s_prod = Settings(_env_file=str(sentinel_env))  # type: ignore[call-arg]
    assert "from_dotenv" not in s_prod.database_url, (
        f"Production must not load DATABASE_URL from dotenv, got: {s_prod.database_url!r}"
    )

    # ── Development: dotenv must be loaded ───────────────────────────────────
    monkeypatch.setenv("APP_ENV", "development")
    s_dev = Settings(_env_file=str(sentinel_env))  # type: ignore[call-arg]
    assert "from_dotenv" in s_dev.database_url, (
        f"Development must load DATABASE_URL from dotenv, got: {s_dev.database_url!r}"
    )

    # ── Explicit env var overrides dotenv in non-production ──────────────────
    monkeypatch.setenv("DATABASE_URL", "postgresql://explicit:x@localhost/from_env")
    s_override = Settings(_env_file=str(sentinel_env))  # type: ignore[call-arg]
    assert "from_env" in s_override.database_url, (
        f"Explicit env var must win over dotenv, got: {s_override.database_url!r}"
    )
