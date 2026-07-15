"""Integration tests for invitation acceptance by new (unregistered) users.

Covers:
  1. New user can preview an invitation without logging in
  2. Accepting an invitation via accept-new creates account, sets cookies, joins org
  3. Weak password is rejected on accept-new
  4. Expired invitation is rejected on accept-new
  5. Already-accepted invitation is rejected on accept-new
  6. Existing user cannot use the new-user acceptance endpoint
"""

import re
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session as SASession

from app.models.organization import OrganizationInvitation
from app.models.user import User
from tests.integration.conftest import csrf_headers, login, register_and_verify

pytestmark = pytest.mark.integration

_PASSWORD = "TestPassword123!"
_NEW_PASSWORD = "NewUserPassword789!"


def _setup_admin_with_org(http_client, fake_email, email, org_name):
    """Register + verify + login + create org + switch context. Returns csrf headers."""
    register_and_verify(http_client, fake_email, email, password=_PASSWORD)
    login(http_client, email, password=_PASSWORD)
    headers = csrf_headers(http_client)

    resp = http_client.post(
        "/api/v1/workspace/organizations",
        json={"name": org_name},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    org = resp.json()

    resp = http_client.post(
        "/api/v1/auth/switch-org",
        json={"org_id": org["id"]},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return csrf_headers(http_client)


def _extract_invite_token(fake_email, invited_email):
    """Extract the 64-char hex token from the invitation email."""
    sent = fake_email.invitation_message_for(invited_email)
    assert sent is not None, f"No invitation email found for {invited_email}"
    match = re.search(r"invite/([0-9a-f]{64})", sent.text_body)
    assert match, f"No invite token found in email body:\n{sent.text_body}"
    return match.group(1)


# ── 1. New user can preview invitation ───────────────────────────────────────


def test_new_user_can_preview_invitation(
    http_client: TestClient, fake_email, db_session: SASession
):
    headers = _setup_admin_with_org(
        http_client, fake_email, "newuser1_admin@example.com", "Preview Org"
    )
    invited_email = "newuser1_target@example.com"

    resp = http_client.post(
        "/api/v1/workspace/invitations",
        json={"email": invited_email, "role": "reviewer"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text

    token = _extract_invite_token(fake_email, invited_email)

    # Preview requires no auth
    resp = http_client.get(
        f"/api/v1/workspace/invitations/preview?token={token}",
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert "organization_name" in body, f"Response missing organization_name: {body}"
    assert "role" in body, f"Response missing role: {body}"
    assert "invited_email_masked" in body, f"Response missing invited_email_masked: {body}"

    # The masked email must not be the raw email
    assert body["invited_email_masked"] != invited_email, (
        "invited_email_masked must not equal the raw email address"
    )


# ── 2. New user accept creates account and joins org ─────────────────────────


def test_new_user_accept_creates_account_and_joins(
    http_client: TestClient, fake_email, db_session: SASession
):
    from app.main import app

    headers = _setup_admin_with_org(
        http_client, fake_email, "newuser2_admin@example.com", "Accept Org"
    )
    invited_email = "brand_new@example.com"

    resp = http_client.post(
        "/api/v1/workspace/invitations",
        json={"email": invited_email, "role": "recruiter"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text

    token = _extract_invite_token(fake_email, invited_email)

    # Use a fresh client with no prior auth state
    new_client = TestClient(app, raise_server_exceptions=True)
    resp = new_client.post(
        "/api/v1/workspace/invitations/accept-new",
        json={
            "token": token,
            "full_name": "Brand New User",
            "password": _NEW_PASSWORD,
            "terms_accepted": True,
            "privacy_notice_accepted": True,
            "terms_version": "2026-07-01",
            "privacy_notice_version": "2026-07-01",
        },
    )
    assert resp.status_code == 201, resp.text

    # Auth cookies must be set
    assert "es_access" in new_client.cookies, "es_access cookie not set after accept-new"
    assert "es_refresh" in new_client.cookies, "es_refresh cookie not set after accept-new"
    assert "es_csrf" in new_client.cookies, "es_csrf cookie not set after accept-new"

    # The new user can access /auth/me
    resp = new_client.get("/api/v1/auth/me")
    assert resp.status_code == 200, resp.text
    me = resp.json()
    assert me["email"] == invited_email, f"Expected email {invited_email!r}, got {me['email']!r}"

    # Email must be verified automatically upon invitation acceptance
    db_session.expire_all()
    user = db_session.query(User).filter(User.email == invited_email).first()
    assert user is not None, f"User {invited_email!r} not found in DB"
    assert user.email_verified is True, (
        "email_verified must be True after accepting an invitation as a new user"
    )


# ── 3. Weak password rejected on accept-new ──────────────────────────────────


def test_new_user_accept_weak_password_rejected(
    http_client: TestClient, fake_email, db_session: SASession
):
    headers = _setup_admin_with_org(
        http_client, fake_email, "newuser3_admin@example.com", "Weak PW Org"
    )
    invited_email = "newuser3_target@example.com"

    resp = http_client.post(
        "/api/v1/workspace/invitations",
        json={"email": invited_email, "role": "recruiter"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text

    token = _extract_invite_token(fake_email, invited_email)

    resp = http_client.post(
        "/api/v1/workspace/invitations/accept-new",
        json={
            "token": token,
            "full_name": "Weak PW User",
            "password": "short",  # too weak
            "terms_accepted": True,
            "privacy_notice_accepted": True,
            "terms_version": "2026-07-01",
            "privacy_notice_version": "2026-07-01",
        },
    )
    assert resp.status_code == 422, (
        f"Expected 422 for weak password, got {resp.status_code}: {resp.text}"
    )


# ── 4. Expired invitation rejected on accept-new ─────────────────────────────


def test_new_user_accept_expired_invitation_rejected(
    http_client: TestClient, fake_email, db_session: SASession
):
    headers = _setup_admin_with_org(
        http_client, fake_email, "newuser4_admin@example.com", "Expired Org"
    )
    invited_email = "newuser4_target@example.com"

    resp = http_client.post(
        "/api/v1/workspace/invitations",
        json={"email": invited_email, "role": "recruiter"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text

    token = _extract_invite_token(fake_email, invited_email)

    # Expire the invitation by setting expires_at in the past
    db_session.expire_all()
    inv = (
        db_session.query(OrganizationInvitation)
        .filter(OrganizationInvitation.email == invited_email)
        .first()
    )
    assert inv is not None
    inv.expires_at = datetime.now(UTC) - timedelta(days=1)
    db_session.flush()

    resp = http_client.post(
        "/api/v1/workspace/invitations/accept-new",
        json={
            "token": token,
            "full_name": "Expired Inv User",
            "password": _NEW_PASSWORD,
            "terms_accepted": True,
            "privacy_notice_accepted": True,
            "terms_version": "2026-07-01",
            "privacy_notice_version": "2026-07-01",
        },
    )
    assert resp.status_code == 401, (
        f"Expected 401 for expired invitation, got {resp.status_code}: {resp.text}"
    )
    assert resp.json()["detail"]["error"] == "INVALID_INVITATION", (
        f"Expected error='INVALID_INVITATION', got {resp.json()['detail']!r}"
    )


# ── 5. Already-accepted invitation rejected on second accept ─────────────────


def test_new_user_accept_already_accepted_rejected(
    http_client: TestClient, fake_email, db_session: SASession
):
    headers = _setup_admin_with_org(
        http_client, fake_email, "newuser5_admin@example.com", "Double Accept Org"
    )
    invited_email = "newuser5_target@example.com"

    resp = http_client.post(
        "/api/v1/workspace/invitations",
        json={"email": invited_email, "role": "recruiter"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text

    token = _extract_invite_token(fake_email, invited_email)

    _consent = {
        "terms_accepted": True,
        "privacy_notice_accepted": True,
        "terms_version": "2026-07-01",
        "privacy_notice_version": "2026-07-01",
    }

    # First acceptance — should succeed
    resp = http_client.post(
        "/api/v1/workspace/invitations/accept-new",
        json={
            "token": token,
            "full_name": "Already Accepted User",
            "password": _NEW_PASSWORD,
            **_consent,
        },
    )
    assert resp.status_code == 201, resp.text

    # Second acceptance with the same token — must fail
    resp = http_client.post(
        "/api/v1/workspace/invitations/accept-new",
        json={
            "token": token,
            "full_name": "Already Accepted User",
            "password": _NEW_PASSWORD,
            **_consent,
        },
    )
    assert resp.status_code == 401, (
        f"Expected 401 for already-accepted invitation, got {resp.status_code}: {resp.text}"
    )
    assert resp.json()["detail"]["error"] == "INVALID_INVITATION", (
        f"Expected error='INVALID_INVITATION', got {resp.json()['detail']!r}"
    )


# ── 6. Existing user cannot use new-user endpoint ────────────────────────────


def test_existing_user_cannot_use_new_user_endpoint(
    http_client: TestClient, fake_email, db_session: SASession
):
    existing_email = "existing@example.com"
    register_and_verify(http_client, fake_email, existing_email, password=_PASSWORD)

    # Login as admin and create an invitation for the existing user's email
    headers = _setup_admin_with_org(
        http_client, fake_email, "newuser6_admin@example.com", "Existing User Org"
    )

    resp = http_client.post(
        "/api/v1/workspace/invitations",
        json={"email": existing_email, "role": "recruiter"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text

    token = _extract_invite_token(fake_email, existing_email)

    # Attempt to accept via accept-new using the existing email
    resp = http_client.post(
        "/api/v1/workspace/invitations/accept-new",
        json={
            "token": token,
            "full_name": "Existing User",
            "password": _NEW_PASSWORD,
            "terms_accepted": True,
            "privacy_notice_accepted": True,
            "terms_version": "2026-07-01",
            "privacy_notice_version": "2026-07-01",
        },
    )
    assert resp.status_code == 409, (
        f"Expected 409 when existing user uses accept-new, got {resp.status_code}: {resp.text}"
    )
    assert resp.json()["detail"]["error"] == "EMAIL_ALREADY_EXISTS", (
        f"Expected error='EMAIL_ALREADY_EXISTS', got {resp.json()['detail']!r}"
    )
