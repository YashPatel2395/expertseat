"""Integration tests for email verification."""

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration


def test_valid_code_verifies_email(http_client: TestClient, fake_email):
    import re

    http_client.post(
        "/api/v1/auth/register",
        json={
            "email": "verify@example.com",
            "password": "Password123!",
            "full_name": "Verify User",
        },
    )
    sent = fake_email.last_to("verify@example.com")
    m = re.search(r"\b(\d{6})\b", sent.text_body)
    assert m, "No 6-digit code in email"
    code = m.group(1)
    resp = http_client.post(
        "/api/v1/auth/verify-email",
        json={
            "email": "verify@example.com",
            "code": code,
        },
    )
    assert resp.status_code == 200
    assert "verified" in resp.json()["message"].lower()


def test_wrong_code_returns_401(http_client: TestClient, fake_email):
    http_client.post(
        "/api/v1/auth/register",
        json={
            "email": "badcode@example.com",
            "password": "Password123!",
            "full_name": "Bad Code",
        },
    )
    resp = http_client.post(
        "/api/v1/auth/verify-email",
        json={
            "email": "badcode@example.com",
            "code": "000000",
        },
    )
    assert resp.status_code == 401
    assert resp.json()["detail"]["error"] == "INVALID_VERIFICATION_CODE"


def test_unknown_email_returns_200_safe_response(http_client: TestClient, fake_email):
    """Email enumeration prevention: unknown email must return 200."""
    resp = http_client.post(
        "/api/v1/auth/verify-email",
        json={
            "email": "nobody@example.com",
            "code": "123456",
        },
    )
    assert resp.status_code == 200


def test_already_used_code_returns_401(http_client: TestClient, fake_email):
    import re

    http_client.post(
        "/api/v1/auth/register",
        json={
            "email": "usedcode@example.com",
            "password": "Password123!",
            "full_name": "Used Code",
        },
    )
    sent = fake_email.last_to("usedcode@example.com")
    m2 = re.search(r"\b(\d{6})\b", sent.text_body)
    assert m2, "No 6-digit code in email"
    code = m2.group(1)
    # Use it once
    http_client.post(
        "/api/v1/auth/verify-email", json={"email": "usedcode@example.com", "code": code}
    )
    # Use it again
    resp = http_client.post(
        "/api/v1/auth/verify-email", json={"email": "usedcode@example.com", "code": code}
    )
    assert resp.status_code == 401
