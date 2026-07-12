import pytest

from app.config import Settings


def test_default_settings():
    s = Settings()
    assert s.app_name == "ExpertSeat API"
    assert s.app_env == "development"


def test_invalid_env():
    with pytest.raises(Exception):
        Settings(app_env="invalid")
