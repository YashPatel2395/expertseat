"""Integration tests for invitation endpoint rate limiting.

Invariants verified:
  1. invitation-create rate limit is enforced per IP window
  2. invitation-accept rate limit is enforced per IP window
  3. invitation-accept-new rate limit is enforced per IP window
  4. invitation-resend rate limit is enforced per IP window
  5. Retry-After header is present on 429 responses
  6. Auth and invitation rate limits use separate key namespaces
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session as SASession

from tests.integration.conftest import csrf_headers, login, register_and_verify

pytestmark = pytest.mark.integration

_PASSWORD = "TestPassword123!"


def _setup_org_with_invite_capacity(http_client, fake_email, admin_email, org_name):
    """Register admin, create org, switch context. Returns csrf headers and org_id."""
    register_and_verify(http_client, fake_email, admin_email, password=_PASSWORD)
    login(http_client, email=admin_email, password=_PASSWORD)
    headers = csrf_headers(http_client)

    resp = http_client.post(
        "/api/v1/workspace/organizations",
        json={"name": org_name},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    org_id = resp.json()["id"]

    resp = http_client.post(
        "/api/v1/auth/switch-org",
        json={"org_id": org_id},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return csrf_headers(http_client), org_id


# ── 1. invitation-create rate limit ────────────────────────────────────────────


def test_invitation_create_rate_limit(http_client: TestClient, fake_email, db_session: SASession):
    """Exceeding rate_limit_invitation_max invitations triggers 429."""
    from app.config import settings

    headers, _ = _setup_org_with_invite_capacity(
        http_client, fake_email, "rl_create_admin@example.com", "RL Create Org"
    )

    status_codes = []
    for i in range(settings.rate_limit_invitation_max + 2):
        resp = http_client.post(
            "/api/v1/workspace/invitations",
            json={"email": f"invite_target_{i}@example.com", "role": "recruiter"},
            headers=headers,
        )
        status_codes.append(resp.status_code)

    assert 429 in status_codes, (
        f"Expected at least one 429 after {settings.rate_limit_invitation_max} invitations; "
        f"got status codes: {status_codes}"
    )


# ── 2. invitation-accept rate limit ────────────────────────────────────────────


def test_invitation_accept_rate_limit(http_client: TestClient, fake_email, db_session: SASession):
    """Exceeding rate_limit_invitation_max accept attempts triggers 429."""
    from app.config import settings

    register_and_verify(http_client, fake_email, "rl_accept_user@example.com", password=_PASSWORD)
    login(http_client, "rl_accept_user@example.com", password=_PASSWORD)
    headers = csrf_headers(http_client)

    status_codes = []
    for _ in range(settings.rate_limit_invitation_max + 2):
        resp = http_client.post(
            "/api/v1/workspace/invitations/accept",
            json={"token": "a" * 64},
            headers=headers,
        )
        status_codes.append(resp.status_code)

    assert 429 in status_codes, (
        f"Expected at least one 429 on repeated accept attempts; got: {status_codes}"
    )


# ── 3. invitation-accept-new rate limit ────────────────────────────────────────


def test_invitation_accept_new_rate_limit(
    http_client: TestClient, fake_email, db_session: SASession
):
    """Exceeding rate_limit_invitation_max accept-new attempts triggers 429."""
    from app.config import settings

    status_codes = []
    for _ in range(settings.rate_limit_invitation_max + 2):
        resp = http_client.post(
            "/api/v1/workspace/invitations/accept-new",
            json={
                "token": "a" * 64,
                "full_name": "Test",
                "password": _PASSWORD,
                "terms_accepted": True,
                "privacy_notice_accepted": True,
                "terms_version": "2026-07-01",
                "privacy_notice_version": "2026-07-01",
            },
        )
        status_codes.append(resp.status_code)

    assert 429 in status_codes, (
        f"Expected at least one 429 on repeated accept-new attempts; got: {status_codes}"
    )


# ── 4. invitation-resend rate limit ────────────────────────────────────────────


def test_invitation_resend_rate_limit(http_client: TestClient, fake_email, db_session: SASession):
    """Exceeding rate_limit_invitation_max resend attempts triggers 429."""
    from app.config import settings

    headers, _ = _setup_org_with_invite_capacity(
        http_client, fake_email, "rl_resend_admin@example.com", "RL Resend Org"
    )

    import uuid as _uuid

    status_codes = []
    for _ in range(settings.rate_limit_invitation_max + 2):
        resp = http_client.post(
            f"/api/v1/workspace/invitations/{_uuid.uuid4()}/resend",
            headers=headers,
        )
        status_codes.append(resp.status_code)

    assert 429 in status_codes, (
        f"Expected at least one 429 on repeated resend attempts; got: {status_codes}"
    )


# ── 5. 429 response includes Retry-After header ────────────────────────────────


def test_invitation_rate_limit_includes_retry_after(
    http_client: TestClient, fake_email, db_session: SASession
):
    """429 responses from invitation endpoints must include Retry-After header."""
    from app.config import settings

    status_codes_and_headers = []
    for _ in range(settings.rate_limit_invitation_max + 2):
        resp = http_client.post(
            "/api/v1/workspace/invitations/accept-new",
            json={
                "token": "b" * 64,
                "full_name": "Test",
                "password": _PASSWORD,
                "terms_accepted": True,
                "privacy_notice_accepted": True,
                "terms_version": "2026-07-01",
                "privacy_notice_version": "2026-07-01",
            },
        )
        status_codes_and_headers.append((resp.status_code, dict(resp.headers)))

    rate_limited = [(s, h) for s, h in status_codes_and_headers if s == 429]
    assert rate_limited, "Expected at least one 429 response"

    for _, headers in rate_limited:
        assert "retry-after" in {k.lower() for k in headers}, (
            f"429 response missing Retry-After header; headers: {headers}"
        )


# ── 6. Auth and invitation limits use separate namespaces ──────────────────────


def test_auth_and_invitation_rate_limits_are_independent(
    http_client: TestClient, fake_email, db_session: SASession
):
    """Exhausting auth rate limit must not affect invitation limit and vice versa."""
    from app.config import settings

    email = "rl_independent@example.com"
    register_and_verify(http_client, fake_email, email, password=_PASSWORD)

    # Exhaust auth limit with failed logins
    for _ in range(settings.rate_limit_auth_max + 1):
        resp = http_client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "WrongPassword999!"},
        )
        if resp.status_code == 429:
            break

    # Invitation accept-new must still be reachable (not 429 from auth exhaustion)
    resp = http_client.post(
        "/api/v1/workspace/invitations/accept-new",
        json={
            "token": "c" * 64,
            "full_name": "Test",
            "password": _PASSWORD,
            "terms_accepted": True,
            "privacy_notice_accepted": True,
            "terms_version": "2026-07-01",
            "privacy_notice_version": "2026-07-01",
        },
    )
    # Must get 401 (invalid token) NOT 429 (rate limited) or 503 (auth limit applied)
    assert resp.status_code != 429, (
        "Invitation endpoint must not be rate-limited by auth exhaustion "
        f"(separate namespaces); got {resp.status_code}: {resp.text}"
    )
    assert resp.status_code != 503, f"Invitation endpoint returned 503 unexpectedly: {resp.text}"
