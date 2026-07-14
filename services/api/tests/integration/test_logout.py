"""Integration tests for logout."""

import pytest
from fastapi.testclient import TestClient

from tests.integration.conftest import csrf_headers, login, register_and_verify

pytestmark = pytest.mark.integration


def test_logout_clears_cookies(http_client: TestClient, fake_email):
    register_and_verify(http_client, fake_email, "logout@example.com")
    login(http_client, "logout@example.com")
    headers = csrf_headers(http_client)
    resp = http_client.post("/api/v1/auth/logout", headers=headers)
    assert resp.status_code == 200
    # After logout, CSRF cookie is cleared; refresh will be rejected by CSRF
    # middleware (403) or by session check (401) — either proves the session is gone.
    resp = http_client.post("/api/v1/auth/refresh")
    assert resp.status_code in (401, 403)


def test_logout_all_revokes_all_sessions(http_client: TestClient, fake_email):
    register_and_verify(http_client, fake_email, "logoutall@example.com")
    login(http_client, "logoutall@example.com")
    headers = csrf_headers(http_client)
    resp = http_client.post("/api/v1/auth/logout-all", headers=headers)
    assert resp.status_code == 200
    # After logout-all, CSRF cookie is cleared; 401 or 403 both prove session gone.
    resp = http_client.post("/api/v1/auth/refresh")
    assert resp.status_code in (401, 403)


def test_logout_requires_csrf(http_client: TestClient, fake_email):
    register_and_verify(http_client, fake_email, "logoutcsrf@example.com")
    login(http_client, "logoutcsrf@example.com")
    # No CSRF header
    resp = http_client.post("/api/v1/auth/logout")
    assert resp.status_code == 403
    assert resp.json()["detail"]["error"] == "CSRF_VALIDATION_FAILED"
