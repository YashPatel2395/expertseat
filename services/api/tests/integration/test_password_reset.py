"""Integration tests for password reset flow."""

import re

import pytest
from fastapi.testclient import TestClient

from tests.integration.conftest import register_and_verify

pytestmark = pytest.mark.integration


def test_full_password_reset_flow(http_client: TestClient, fake_email):
    email = "resetpw@example.com"
    register_and_verify(http_client, fake_email, email)

    resp = http_client.post("/api/v1/auth/forgot-password", json={"email": email})
    assert resp.status_code == 200

    sent = fake_email.last_to(email)
    assert sent is not None
    match = re.search(r"/reset-password\?token=([0-9a-f]{64})", sent.text_body)
    assert match, f"No reset token in email: {sent.text_body}"
    token = match.group(1)

    resp = http_client.post(
        "/api/v1/auth/reset-password",
        json={
            "token": token,
            "new_password": "NewPassword456!",
        },
    )
    assert resp.status_code == 200

    # Old password should no longer work
    resp = http_client.post("/api/v1/auth/login", json={"email": email, "password": "Password123!"})
    assert resp.status_code == 401

    # New password should work
    resp = http_client.post(
        "/api/v1/auth/login", json={"email": email, "password": "NewPassword456!"}
    )
    assert resp.status_code == 200


def test_expired_token_returns_401(http_client: TestClient, fake_email, db_session):
    email = "expiredtoken@example.com"
    register_and_verify(http_client, fake_email, email)
    http_client.post("/api/v1/auth/forgot-password", json={"email": email})

    sent = fake_email.last_to(email)
    match = re.search(r"/reset-password\?token=([0-9a-f]{64})", sent.text_body)
    assert match, "No reset token found in email"
    token = match.group(1)

    # Manually expire the token
    from datetime import UTC, datetime, timedelta

    from app.models.user import PasswordResetToken

    token_bytes = bytes.fromhex(token)
    from app.auth.crypto import sha256_hex

    token_hash = sha256_hex(token_bytes)
    prt = (
        db_session.query(PasswordResetToken)
        .filter(PasswordResetToken.token_hash == token_hash)
        .first()
    )
    assert prt is not None
    prt.expires_at = datetime.now(tz=UTC) - timedelta(hours=2)
    db_session.flush()

    resp = http_client.post(
        "/api/v1/auth/reset-password",
        json={
            "token": token,
            "new_password": "NewPassword456!",
        },
    )
    assert resp.status_code == 401
    assert resp.json()["detail"]["error"] == "INVALID_RESET_TOKEN"


def test_forgot_password_unknown_email_returns_200(http_client: TestClient, fake_email):
    """Enumeration prevention: unknown email must return 200."""
    resp = http_client.post("/api/v1/auth/forgot-password", json={"email": "nobody@example.com"})
    assert resp.status_code == 200
    assert fake_email.last_to("nobody@example.com") is None
