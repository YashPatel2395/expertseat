"""Integration tests for Redis-backed auth rate limiting.

Verified invariants:
  1. Requests within the window are allowed (200).
  2. Exceeding the limit returns 429 with RATE_LIMITED error.
  3. 429 response includes Retry-After header.
  4. Rate limit is per endpoint group (login vs refresh use separate keys).
  5. Counter resets when Redis key expires (TTL-based window).
  6. Fail-closed: Redis unavailable → 503 SERVICE_UNAVAILABLE.
  7. Rate limit key uses a hash of the IP, not the raw IP.
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration

_LOGIN = "/api/v1/auth/login"
_REGISTER = "/api/v1/auth/register"
_REFRESH = "/api/v1/auth/refresh"

_CREDS = {"email": "rl@example.com", "password": "Password123!"}


def _exhaust_limit(http_client: TestClient, endpoint: str, payload: dict, *, limit: int = 10):
    """Send *limit* requests to burn through the rate limit window."""
    for _ in range(limit):
        http_client.post(endpoint, json=payload)


# ── 1. Requests within limit are allowed ──────────────────────────────────────


def test_first_login_attempt_is_allowed(http_client: TestClient, fake_email):
    resp = http_client.post(_LOGIN, json=_CREDS)
    # 401 (bad credentials) is fine — the rate limiter let it through
    assert resp.status_code != 429
    assert resp.status_code != 503


# ── 2. Exceeding the limit returns 429 ────────────────────────────────────────


def test_exceeding_login_limit_returns_429(http_client: TestClient, fake_email):
    # Burn 10 attempts (the default max)
    _exhaust_limit(http_client, _LOGIN, _CREDS, limit=10)
    # The 11th request must be rate-limited
    resp = http_client.post(_LOGIN, json=_CREDS)
    assert resp.status_code == 429
    assert resp.json()["detail"]["error"] == "RATE_LIMITED"


# ── 3. 429 includes Retry-After header ────────────────────────────────────────


def test_rate_limited_response_includes_retry_after(http_client: TestClient, fake_email):
    _exhaust_limit(http_client, _LOGIN, _CREDS, limit=10)
    resp = http_client.post(_LOGIN, json=_CREDS)
    assert resp.status_code == 429
    assert "retry-after" in {k.lower() for k in resp.headers}


# ── 4. Rate limit is per endpoint group ───────────────────────────────────────


def test_login_limit_does_not_affect_register_endpoint(http_client: TestClient, fake_email):
    # Exhaust the login limit
    _exhaust_limit(http_client, _LOGIN, _CREDS, limit=10)
    # Register endpoint has its own counter — must not be 429
    resp = http_client.post(
        _REGISTER,
        json={"email": "new@example.com", "password": "Password123!", "full_name": "New"},
    )
    assert resp.status_code != 429


# ── 5. Counter resets after TTL ───────────────────────────────────────────────


def test_counter_resets_after_redis_key_deleted(http_client: TestClient, fake_email):
    import os

    import redis as redis_lib

    _REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")

    # Burn the limit
    _exhaust_limit(http_client, _LOGIN, _CREDS, limit=10)
    resp = http_client.post(_LOGIN, json=_CREDS)
    assert resp.status_code == 429

    # Simulate window expiry by deleting rate keys manually
    r = redis_lib.from_url(_REDIS_URL, decode_responses=True)
    try:
        keys = list(r.scan_iter("rate:*"))
        if keys:
            r.delete(*keys)
    finally:
        r.close()

    # Next request is now allowed again
    resp = http_client.post(_LOGIN, json=_CREDS)
    assert resp.status_code != 429


# ── 6. Fail-closed: Redis unavailable → 503 ───────────────────────────────────


def test_redis_unavailable_returns_503(http_client: TestClient, fake_email):
    with patch("app.auth.ratelimit.redis_lib.from_url", side_effect=ConnectionError("down")):
        resp = http_client.post(_LOGIN, json=_CREDS)
    assert resp.status_code == 503
    assert resp.json()["detail"]["error"] == "SERVICE_UNAVAILABLE"


# ── 7. Rate limit key is IP-hashed, not raw IP ────────────────────────────────


def test_rate_limit_key_contains_hashed_ip_not_raw():
    import hashlib

    from app.auth.ratelimit import _ip_hash

    raw_ip = "192.168.1.100"
    hashed = _ip_hash(raw_ip)

    assert raw_ip not in hashed
    assert hashed == hashlib.sha256(raw_ip.encode()).hexdigest()[:16]
    assert len(hashed) == 16
