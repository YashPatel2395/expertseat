"""Integration tests for password length policy (12–128 characters).

Covers the registration endpoint and the reset-password endpoint, both of
which must enforce the same policy.
"""

import re

import pytest
from fastapi.testclient import TestClient

from tests.integration.conftest import register_and_verify

pytestmark = pytest.mark.integration

_REGISTER = "/api/v1/auth/register"


def test_password_11_chars_rejected(http_client: TestClient, fake_email):
    """Passwords shorter than 12 characters must be rejected with 422."""
    resp = http_client.post(
        _REGISTER,
        json={
            "email": "pwtest11@example.com",
            "password": "Ab3!Ab3!Ab3",  # 11 chars
            "full_name": "Test User",
        },
    )
    assert resp.status_code == 422


def test_password_12_chars_accepted(http_client: TestClient, fake_email):
    """A password of exactly 12 characters must be accepted."""
    resp = http_client.post(
        _REGISTER,
        json={
            "email": "pwtest12@example.com",
            "password": "Ab3!Ab3!Ab3!",  # exactly 12 chars
            "full_name": "Test User",
        },
    )
    assert resp.status_code == 201


def test_password_128_chars_accepted(http_client: TestClient, fake_email):
    """A password of exactly 128 characters must be accepted."""
    resp = http_client.post(
        _REGISTER,
        json={
            "email": "pwtest128@example.com",
            "password": "a" * 128,
            "full_name": "Test User",
        },
    )
    assert resp.status_code == 201


def test_password_129_chars_rejected(http_client: TestClient, fake_email):
    """Passwords longer than 128 characters must be rejected with 422."""
    resp = http_client.post(
        _REGISTER,
        json={
            "email": "pwtest129@example.com",
            "password": "a" * 129,
            "full_name": "Test User",
        },
    )
    assert resp.status_code == 422


def test_unicode_passphrase_accepted(http_client: TestClient, fake_email):
    """Unicode passphrases longer than 12 characters must be accepted."""
    resp = http_client.post(
        _REGISTER,
        json={
            "email": "pwtest_unicode@example.com",
            "password": "correct horse battery staple 正確的馬電池釘",
            "full_name": "Test User",
        },
    )
    assert resp.status_code == 201


def test_password_not_in_response(http_client: TestClient, fake_email):
    """The plaintext password must never appear in any part of the API response."""
    password = "SecurePass123!"
    resp = http_client.post(
        _REGISTER,
        json={
            "email": "pwtest_noleak@example.com",
            "password": password,
            "full_name": "Test User",
        },
    )
    assert resp.status_code == 201
    response_text = resp.text
    assert password not in response_text


def test_reset_password_enforces_policy(http_client: TestClient, fake_email, db_session):
    """The reset-password endpoint must enforce the same 12–128 char policy."""
    email = "pwreset_policy@example.com"
    register_and_verify(http_client, fake_email, email)

    resp = http_client.post("/api/v1/auth/forgot-password", json={"email": email})
    assert resp.status_code == 200

    sent = fake_email.last_to(email)
    assert sent is not None, "No password reset email received"
    match = re.search(r"/reset-password\?token=([0-9a-f]{64})", sent.text_body)
    assert match, f"No reset token in email body: {sent.text_body}"
    token = match.group(1)

    # 11-char password should fail
    resp = http_client.post(
        "/api/v1/auth/reset-password",
        json={"token": token, "new_password": "Ab3!Ab3!Ab3"},  # 11 chars
    )
    assert resp.status_code == 422

    # 12-char password should succeed with the same token
    resp = http_client.post(
        "/api/v1/auth/reset-password",
        json={"token": token, "new_password": "Ab3!Ab3!Ab3!"},  # 12 chars
    )
    assert resp.status_code == 200
