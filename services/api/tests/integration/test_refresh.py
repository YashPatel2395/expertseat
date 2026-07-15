"""Integration tests for token refresh."""

import pytest
from fastapi.testclient import TestClient

from tests.integration.conftest import csrf_headers, login, register_and_verify

pytestmark = pytest.mark.integration

_REFRESH = "/api/v1/auth/refresh"


def test_refresh_issues_new_access_cookie(http_client: TestClient, fake_email):
    register_and_verify(http_client, fake_email, "refresh@example.com")
    login(http_client, "refresh@example.com")
    original_access = http_client.cookies.get("es_access")
    resp = http_client.post(_REFRESH, headers=csrf_headers(http_client))
    assert resp.status_code == 200
    new_access = http_client.cookies.get("es_access")
    assert new_access != original_access
    # Access token is set in cookie only — not returned in JSON
    assert "access_token" not in resp.json()


def test_refresh_rotates_refresh_token(http_client: TestClient, fake_email):
    register_and_verify(http_client, fake_email, "refreshrot@example.com")
    login(http_client, "refreshrot@example.com")
    old_refresh = http_client.cookies.get("es_refresh")
    http_client.post(_REFRESH, headers=csrf_headers(http_client))
    new_refresh = http_client.cookies.get("es_refresh")
    assert new_refresh != old_refresh


def test_missing_refresh_cookie_returns_401(http_client: TestClient, fake_email):
    # Need a CSRF cookie first — register and login to get one
    register_and_verify(http_client, fake_email, "norefresh@example.com")
    login(http_client, "norefresh@example.com")
    # Remove the refresh cookie
    http_client.cookies.delete("es_refresh")
    resp = http_client.post(_REFRESH, headers=csrf_headers(http_client))
    assert resp.status_code == 401


def test_refresh_without_csrf_returns_403(http_client: TestClient, fake_email):
    """Refresh without CSRF token must be rejected."""
    register_and_verify(http_client, fake_email, "csrfrefresh@example.com")
    login(http_client, "csrfrefresh@example.com")
    resp = http_client.post(_REFRESH)  # no CSRF header
    assert resp.status_code == 403
    assert resp.json()["detail"]["error"] == "CSRF_VALIDATION_FAILED"


def test_refresh_with_mismatched_csrf_returns_403(http_client: TestClient, fake_email):
    """Refresh with wrong CSRF token must be rejected."""
    register_and_verify(http_client, fake_email, "badcsrf@example.com")
    login(http_client, "badcsrf@example.com")
    resp = http_client.post(_REFRESH, headers={"X-CSRF-Token": "wrong-token"})
    assert resp.status_code == 403


def test_replay_detection_revokes_family(http_client: TestClient, fake_email):
    """Using an already-rotated refresh token must revoke the entire family."""
    register_and_verify(http_client, fake_email, "replay@example.com")
    login(http_client, "replay@example.com")
    old_refresh = http_client.cookies.get("es_refresh")

    # First refresh — legitimate
    http_client.post(_REFRESH, headers=csrf_headers(http_client))

    # Restore old refresh token to simulate attacker replaying it
    http_client.cookies.set("es_refresh", old_refresh)
    resp = http_client.post(_REFRESH, headers=csrf_headers(http_client))
    assert resp.status_code == 401
    assert resp.json()["detail"]["error"] == "REFRESH_TOKEN_REUSED"
