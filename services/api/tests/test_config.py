import pytest

from app.config import Settings


def test_default_settings(monkeypatch):
    # Explicitly clear environment variables that pydantic-settings would pick up,
    # so the test is not sensitive to whatever APP_ENV the CI runner sets.
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    s = Settings()
    assert s.app_name == "ExpertSeat API"
    assert s.app_env == "development"


def test_explicit_env_override(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    s = Settings()
    assert s.app_env == "test"


def test_invalid_env():
    with pytest.raises(Exception):
        Settings(app_env="invalid")
