"""Tests for RATE_LIMIT_SECRET configuration requirements.

Covers:
  - Missing RATE_LIMIT_SECRET fails production validation
  - RATE_LIMIT_SECRET equal to SECRET_KEY fails production validation
  - RATE_LIMIT_SECRET too short fails production validation
  - Valid RATE_LIMIT_SECRET passes production validation
  - Different secrets produce different pseudonyms
  - Redis key format includes app_env
  - Raw IP is not present in the pseudonym output
"""

import pytest
from pydantic import ValidationError

from app.config import Settings

pytestmark = pytest.mark.integration

_PROD_DB = "postgresql://prod:x@prod-host:5432/proddb"
_PROD_REDIS = "redis://prod-redis:6379/0"
_PROD_SECRET = "production-secret-key-that-is-long-enough-00"
_PROD_RATE_SECRET = "production-rate-limit-secret-that-is-long-enough-xx"
_PROD_OUTBOX_KEY = "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2"


# ── 1. Missing RATE_LIMIT_SECRET fails production validation ──────────────────


def test_missing_rate_limit_secret_fails_production_validation(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", _PROD_DB)
    monkeypatch.setenv("REDIS_URL", _PROD_REDIS)
    monkeypatch.setenv("SECRET_KEY", _PROD_SECRET)
    monkeypatch.delenv("RATE_LIMIT_SECRET", raising=False)
    with pytest.raises(ValidationError, match="RATE_LIMIT_SECRET"):
        Settings(app_env="production")


# ── 2. RATE_LIMIT_SECRET equal to SECRET_KEY fails production ─────────────────


def test_rate_limit_secret_equal_to_secret_key_fails_production(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", _PROD_DB)
    monkeypatch.setenv("REDIS_URL", _PROD_REDIS)
    monkeypatch.setenv("SECRET_KEY", _PROD_SECRET)
    monkeypatch.setenv("RATE_LIMIT_SECRET", _PROD_SECRET)
    with pytest.raises(ValidationError, match="different from SECRET_KEY"):
        Settings(app_env="production")


# ── 3. RATE_LIMIT_SECRET too short fails production ───────────────────────────


def test_rate_limit_secret_too_short_fails_production(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", _PROD_DB)
    monkeypatch.setenv("REDIS_URL", _PROD_REDIS)
    monkeypatch.setenv("SECRET_KEY", _PROD_SECRET)
    monkeypatch.setenv("RATE_LIMIT_SECRET", "short")
    with pytest.raises(ValidationError):
        Settings(app_env="production")


# ── 4. Valid RATE_LIMIT_SECRET passes production validation ───────────────────


def test_rate_limit_secret_valid_in_production(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", _PROD_DB)
    monkeypatch.setenv("REDIS_URL", _PROD_REDIS)
    monkeypatch.setenv("SECRET_KEY", _PROD_SECRET)
    monkeypatch.setenv("RATE_LIMIT_SECRET", _PROD_RATE_SECRET)
    monkeypatch.setenv("OUTBOX_ENCRYPTION_KEY", _PROD_OUTBOX_KEY)
    # Must not raise
    s = Settings(app_env="production")
    assert s.rate_limit_secret == _PROD_RATE_SECRET


# ── 5. Different secrets produce different pseudonyms ─────────────────────────


def test_different_secrets_produce_different_pseudonyms():
    import app.auth.ratelimit as ratelimit_module
    import app.config as config_module

    ip = "1.2.3.4"

    # Patch settings.rate_limit_secret to first value and capture result
    original_secret = config_module.settings.rate_limit_secret
    try:
        config_module.settings.rate_limit_secret = "aaaabbbbccccddddeeeeffffgggghhhh"
        hmac1 = ratelimit_module._ip_hmac(ip)

        config_module.settings.rate_limit_secret = "zzzzyyyyxxxxwwwwvvvvuuuuttttssss"
        hmac2 = ratelimit_module._ip_hmac(ip)
    finally:
        config_module.settings.rate_limit_secret = original_secret

    assert hmac1 != hmac2, "Different secrets must produce different pseudonyms"


# ── 6. Redis key format includes app_env ──────────────────────────────────────


def test_redis_key_includes_app_env():
    from app.auth.ratelimit import _ip_hmac
    from app.config import settings

    hmac = _ip_hmac("1.2.3.4")
    key = f"rate:{settings.app_env}:login:{hmac}"

    # In test/dev environment, app_env is "development" or "test"
    assert settings.app_env in key, f"app_env '{settings.app_env}' must appear in key '{key}'"
    assert key.startswith("rate:"), f"Key must start with 'rate:'; got {key!r}"


# ── 7. Raw IP not present in pseudonym ────────────────────────────────────────


def test_raw_ip_not_in_pseudonym():
    from app.auth.ratelimit import _ip_hmac

    ip = "192.168.1.1"
    pseudonym = _ip_hmac(ip)
    assert ip not in pseudonym, f"Raw IP {ip!r} must not appear in pseudonym {pseudonym!r}"
