"""Integration tests for token refresh and replay detection."""

import pytest
from fastapi.testclient import TestClient

from tests.integration.conftest import login, register_and_verify

pytestmark = pytest.mark.integration


def test_refresh_issues_new_access_token(http_client: TestClient, fake_email):
    register_and_verify(http_client, fake_email, "refresh@example.com")
    login(http_client, "refresh@example.com")
    original_access = http_client.cookies.get("es_access")
    resp = http_client.post("/api/v1/auth/refresh")
    assert resp.status_code == 200
    new_access = http_client.cookies.get("es_access")
    assert new_access != original_access


def test_refresh_rotates_refresh_token(http_client: TestClient, fake_email):
    register_and_verify(http_client, fake_email, "refreshrot@example.com")
    login(http_client, "refreshrot@example.com")
    old_refresh = http_client.cookies.get("es_refresh")
    http_client.post("/api/v1/auth/refresh")
    new_refresh = http_client.cookies.get("es_refresh")
    assert new_refresh != old_refresh


def test_missing_refresh_cookie_returns_401(http_client: TestClient, fake_email):
    # Do not log in — no refresh cookie
    resp = http_client.post("/api/v1/auth/refresh")
    assert resp.status_code == 401


def test_replay_detection_revokes_family(http_client: TestClient, fake_email):
    """Using an already-rotated refresh token must revoke the entire family."""
    register_and_verify(http_client, fake_email, "replay@example.com")
    login(http_client, "replay@example.com")

    # Save the original refresh token
    old_refresh = http_client.cookies.get("es_refresh")

    # First refresh — legitimate, rotates the token
    http_client.post("/api/v1/auth/refresh")

    # Restore old refresh token to simulate attacker replaying it
    http_client.cookies.set("es_refresh", old_refresh)

    # Second refresh with stale token — should trigger family revocation
    resp = http_client.post("/api/v1/auth/refresh")
    assert resp.status_code == 401
    assert resp.json()["detail"]["error"] == "REFRESH_TOKEN_REUSED"
