"""Integration tests for user registration."""

import pytest
from fastapi.testclient import TestClient

from app.email.fake import FakeEmailProvider

pytestmark = pytest.mark.integration


def test_register_creates_user_and_sends_email(
    http_client: TestClient, fake_email: FakeEmailProvider
):
    resp = http_client.post(
        "/api/v1/auth/register",
        json={
            "email": "alice@example.com",
            "password": "Password123!",
            "full_name": "Alice Smith",
        },
    )
    assert resp.status_code == 201
    assert "verification code" in resp.json()["message"].lower()

    sent = fake_email.last_to("alice@example.com")
    assert sent is not None
    assert "alice smith" in sent.html_body.lower() or "alice smith" in sent.text_body.lower()


def test_register_duplicate_email_returns_409(
    http_client: TestClient, fake_email: FakeEmailProvider
):
    for _ in range(2):
        resp = http_client.post(
            "/api/v1/auth/register",
            json={
                "email": "bob@example.com",
                "password": "Password123!",
                "full_name": "Bob Jones",
            },
        )
    assert resp.status_code == 409
    assert resp.json()["detail"]["error"] == "EMAIL_ALREADY_EXISTS"


def test_register_invalid_email_returns_422(http_client: TestClient, fake_email: FakeEmailProvider):
    resp = http_client.post(
        "/api/v1/auth/register",
        json={
            "email": "not-an-email",
            "password": "Password123!",
            "full_name": "Test",
        },
    )
    assert resp.status_code == 422


def test_register_short_password_returns_422(
    http_client: TestClient, fake_email: FakeEmailProvider
):
    resp = http_client.post(
        "/api/v1/auth/register",
        json={
            "email": "charlie@example.com",
            "password": "short",
            "full_name": "Charlie",
        },
    )
    assert resp.status_code == 422


def test_register_email_is_case_normalized(http_client: TestClient, fake_email: FakeEmailProvider):
    """Emails must be stored lowercase; mixed-case registration = duplicate."""
    http_client.post(
        "/api/v1/auth/register",
        json={
            "email": "Dave@Example.COM",
            "password": "Password123!",
            "full_name": "Dave",
        },
    )
    resp = http_client.post(
        "/api/v1/auth/register",
        json={
            "email": "dave@example.com",
            "password": "Password123!",
            "full_name": "Dave2",
        },
    )
    assert resp.status_code == 409
