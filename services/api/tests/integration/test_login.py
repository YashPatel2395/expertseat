"""Integration tests for login."""

import pytest
from fastapi.testclient import TestClient

from tests.integration.conftest import register_and_verify

pytestmark = pytest.mark.integration


def test_valid_credentials_set_cookies(http_client: TestClient, fake_email):
    register_and_verify(http_client, fake_email, "login@example.com")
    resp = http_client.post(
        "/api/v1/auth/login",
        json={
            "email": "login@example.com",
            "password": "Password123!",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["access_token"]
    assert "es_access" in http_client.cookies
    assert "es_refresh" in http_client.cookies
    assert "es_csrf" in http_client.cookies


def test_wrong_password_returns_401(http_client: TestClient, fake_email):
    register_and_verify(http_client, fake_email, "wrongpass@example.com")
    resp = http_client.post(
        "/api/v1/auth/login",
        json={
            "email": "wrongpass@example.com",
            "password": "WrongPassword!",
        },
    )
    assert resp.status_code == 401
    assert resp.json()["detail"]["error"] == "INVALID_CREDENTIALS"


def test_unverified_email_returns_401(http_client: TestClient, fake_email):
    http_client.post(
        "/api/v1/auth/register",
        json={
            "email": "unverified@example.com",
            "password": "Password123!",
            "full_name": "Unverified",
        },
    )
    resp = http_client.post(
        "/api/v1/auth/login",
        json={
            "email": "unverified@example.com",
            "password": "Password123!",
        },
    )
    assert resp.status_code == 401
    assert resp.json()["detail"]["error"] == "EMAIL_NOT_VERIFIED"


def test_nonexistent_email_returns_401(http_client: TestClient, fake_email):
    resp = http_client.post(
        "/api/v1/auth/login",
        json={
            "email": "nobody@example.com",
            "password": "Password123!",
        },
    )
    assert resp.status_code == 401
    assert resp.json()["detail"]["error"] == "INVALID_CREDENTIALS"


def test_me_returns_user_info_after_login(http_client: TestClient, fake_email):
    register_and_verify(http_client, fake_email, "me@example.com")
    http_client.post(
        "/api/v1/auth/login", json={"email": "me@example.com", "password": "Password123!"}
    )
    resp = http_client.get("/api/v1/auth/me")
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == "me@example.com"
