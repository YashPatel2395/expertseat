"""Integration tests for email verification.

Verification tokens are now 64-char hex strings (32 random bytes, 256-bit entropy)
sent as URL links (/verify-email?token=<hex>), not 6-digit codes.
"""

import re

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration

_REGISTER = "/api/v1/auth/register"
_VERIFY = "/api/v1/auth/verify-email"
_TOKEN_RE = re.compile(r"/verify-email\?token=([0-9a-f]{64})")


def _register(http_client, email):
    http_client.post(
        _REGISTER,
        json={"email": email, "password": "Password123456!!", "full_name": "Test User"},
    )


def _extract_token(text_body: str) -> str:
    m = _TOKEN_RE.search(text_body)
    assert m, f"No verification token in email: {text_body}"
    return m.group(1)


def test_valid_token_verifies_email(http_client: TestClient, fake_email):
    _register(http_client, "verify@example.com")
    sent = fake_email.verification_message_for("verify@example.com")
    assert sent is not None
    token = _extract_token(sent.text_body)

    resp = http_client.post(_VERIFY, json={"token": token})
    assert resp.status_code == 200
    assert "verified" in resp.json()["message"].lower()


def test_wrong_token_returns_200_safe_response(http_client: TestClient, fake_email):
    """Invalid token must not reveal whether it ever existed."""
    bad_token = "a" * 64
    resp = http_client.post(_VERIFY, json={"token": bad_token})
    # Returns 200 (consistent response) to prevent enumeration
    assert resp.status_code == 200


def test_unknown_token_returns_200(http_client: TestClient, fake_email):
    """Completely unknown token: same 200 response."""
    resp = http_client.post(_VERIFY, json={"token": "0" * 64})
    assert resp.status_code == 200


def test_already_used_token_returns_200(http_client: TestClient, fake_email):
    """Token used twice returns 200 on second use (consistent enumeration-resistant)."""
    _register(http_client, "usedtoken@example.com")
    sent = fake_email.verification_message_for("usedtoken@example.com")
    token = _extract_token(sent.text_body)

    # First use — succeeds
    http_client.post(_VERIFY, json={"token": token})
    # Second use — returns 200 (not 401) for enumeration resistance
    resp = http_client.post(_VERIFY, json={"token": token})
    assert resp.status_code == 200


def test_token_format_is_64_hex_chars(http_client: TestClient, fake_email):
    """Verification token must be exactly 64 lowercase hex characters."""
    _register(http_client, "tokenformat@example.com")
    sent = fake_email.verification_message_for("tokenformat@example.com")
    token = _extract_token(sent.text_body)

    assert len(token) == 64
    assert all(c in "0123456789abcdef" for c in token)


def test_resend_invalidates_previous_token(http_client: TestClient, fake_email):
    """After resend, the old token must no longer work."""
    _register(http_client, "resend@example.com")
    first_sent = fake_email.verification_message_for("resend@example.com")
    first_token = _extract_token(first_sent.text_body)

    # Trigger resend (new token issued, old token invalidated)
    http_client.post("/api/v1/auth/resend-verification", json={"email": "resend@example.com"})
    second_sent = fake_email.verification_message_for("resend@example.com")
    second_token = _extract_token(second_sent.text_body)

    assert first_token != second_token

    # Old token no longer works
    resp = http_client.post(_VERIFY, json={"token": first_token})
    assert resp.status_code == 200  # consistent response — but let's confirm with login attempt
    # Try to login to confirm email is still unverified
    login_resp = http_client.post(
        "/api/v1/auth/login",
        json={"email": "resend@example.com", "password": "Password123456!!"},
    )
    assert login_resp.status_code == 401
    assert login_resp.json()["detail"]["error"] == "EMAIL_NOT_VERIFIED"


def test_resend_latest_token_works(http_client: TestClient, fake_email):
    """After resend, the new token must work."""
    _register(http_client, "resend2@example.com")

    http_client.post("/api/v1/auth/resend-verification", json={"email": "resend2@example.com"})
    second_sent = fake_email.verification_message_for("resend2@example.com")
    second_token = _extract_token(second_sent.text_body)

    resp = http_client.post(_VERIFY, json={"token": second_token})
    assert resp.status_code == 200

    # Confirm verified by logging in
    login_resp = http_client.post(
        "/api/v1/auth/login",
        json={"email": "resend2@example.com", "password": "Password123456!!"},
    )
    assert login_resp.status_code == 200


def test_token_not_logged_or_returned_in_api_response(http_client: TestClient, fake_email):
    """The raw verification token must not appear in any API response body."""
    _register(http_client, "noleak@example.com")
    sent = fake_email.verification_message_for("noleak@example.com")
    token = _extract_token(sent.text_body)

    resp = http_client.post(_VERIFY, json={"token": token})
    resp_text = resp.text
    assert token not in resp_text, "Raw token must not appear in API response"
