"""Integration tests for account/org/membership validation during token refresh.

These tests use the savepoint-wrapped db_session fixture (shared connection).
Changes made via db_session.flush() are immediately visible to the refresh route
because the route shares the same underlying connection — exactly how test_db_auth.py
validates auth dependency re-checks.

Tested invariants:
  1.  Disabled user cannot refresh (ACCOUNT_DISABLED).
  2.  Unverified user cannot refresh (ACCOUNT_UNVERIFIED).
  3.  Disabled organization strips workspace context (rotation succeeds, org_id cleared).
  4.  Disabled membership strips workspace context (rotation succeeds, org_id cleared).
  5.  Expired family cannot refresh (SESSION_EXPIRED).
"""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session as SASession

from app.models.organization import Membership, Organization
from app.models.session import AuthSession
from app.models.user import User
from tests.integration.conftest import csrf_headers, login, register_and_verify

pytestmark = pytest.mark.integration


# ── 1. Disabled user cannot refresh ──────────────────────────────────────────


def test_disabled_user_cannot_refresh(
    http_client: TestClient, fake_email, db_session: SASession
) -> None:
    """Setting is_active=False on a user immediately blocks token refresh."""
    email = "disabled_refresh@example.com"
    register_and_verify(http_client, fake_email, email)
    login(http_client, email)

    # Capture cookies for the refresh call
    refresh_token = http_client.cookies.get("es_refresh")
    csrf_token = http_client.cookies.get("es_csrf")
    assert refresh_token, "No es_refresh cookie after login"
    assert csrf_token, "No es_csrf cookie after login"

    # Disable the user via shared DB session (flush makes it visible to the route)
    user = db_session.query(User).filter(User.email == email).first()
    assert user is not None
    user.is_active = False
    db_session.flush()

    resp = http_client.post("/api/v1/auth/refresh", headers={"X-CSRF-Token": csrf_token})
    assert resp.status_code == 401
    body = resp.json()
    error = body.get("detail", {}).get("error") or body.get("error")
    assert error == "ACCOUNT_DISABLED", f"Expected ACCOUNT_DISABLED, got: {error!r} — body: {body}"


# ── 2. Unverified user cannot refresh ────────────────────────────────────────


def test_unverified_user_cannot_refresh(
    http_client: TestClient, fake_email, db_session: SASession
) -> None:
    """Revoking email_verified after login immediately blocks token refresh."""
    email = "unverified_refresh@example.com"
    register_and_verify(http_client, fake_email, email)
    login(http_client, email)

    refresh_token = http_client.cookies.get("es_refresh")
    csrf_token = http_client.cookies.get("es_csrf")
    assert refresh_token, "No es_refresh cookie after login"
    assert csrf_token, "No es_csrf cookie after login"

    # Revoke email verification via shared DB session
    user = db_session.query(User).filter(User.email == email).first()
    assert user is not None
    user.email_verified = False
    db_session.flush()

    resp = http_client.post("/api/v1/auth/refresh", headers={"X-CSRF-Token": csrf_token})
    assert resp.status_code == 401
    body = resp.json()
    error = body.get("detail", {}).get("error") or body.get("error")
    assert error == "ACCOUNT_UNVERIFIED", (
        f"Expected ACCOUNT_UNVERIFIED, got: {error!r} — body: {body}"
    )


# ── 3. Disabled organization strips workspace context ─────────────────────────


def test_disabled_organization_strips_workspace_context(
    http_client: TestClient, fake_email, db_session: SASession
) -> None:
    """Policy B: inactive org causes refresh to rotate into no-workspace, not reject.

    The session is rotated successfully but the new session carries no org context.
    Subsequent /auth/me returns org_id == "" (empty string, no active workspace).
    """
    email = "disabled_org_refresh@example.com"
    register_and_verify(http_client, fake_email, email)
    login(http_client, email)
    headers = csrf_headers(http_client)

    # Create an org and switch into it so the session has workspace context
    resp = http_client.post(
        "/api/v1/workspace/organizations",
        json={"name": "Disabled Org Test"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    org = resp.json()
    org_id = org["id"]

    resp = http_client.post("/api/v1/auth/switch-org", json={"org_id": org_id}, headers=headers)
    assert resp.status_code == 200, resp.text

    # Confirm workspace is active before disabling
    resp = http_client.get("/api/v1/auth/me")
    assert resp.status_code == 200
    assert resp.json().get("org_id") == org_id

    # Disable the org via shared DB session
    organization = db_session.query(Organization).filter(Organization.id == org_id).first()
    assert organization is not None
    organization.is_active = False
    db_session.flush()

    # Refresh should succeed (rotation is not blocked)
    csrf_token = http_client.cookies.get("es_csrf")
    resp = http_client.post("/api/v1/auth/refresh", headers={"X-CSRF-Token": csrf_token})
    assert resp.status_code == 200, (
        f"Expected 200 on refresh with disabled org, got {resp.status_code}: {resp.text}"
    )

    # After rotation, /auth/me must show no workspace context
    resp = http_client.get("/api/v1/auth/me")
    assert resp.status_code == 200
    me = resp.json()
    assert me.get("org_id") in ("", None), (
        f"Expected empty org_id after disabled-org refresh, got: {me.get('org_id')!r}"
    )


# ── 4. Disabled membership strips workspace context ───────────────────────────


def test_disabled_membership_strips_workspace_context(
    http_client: TestClient, fake_email, db_session: SASession
) -> None:
    """Policy B: inactive membership causes refresh to rotate into no-workspace."""
    email = "disabled_member_refresh@example.com"
    register_and_verify(http_client, fake_email, email)
    login(http_client, email)
    headers = csrf_headers(http_client)

    # Create an org and switch into it
    resp = http_client.post(
        "/api/v1/workspace/organizations",
        json={"name": "Disabled Membership Test"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    org = resp.json()
    org_id = org["id"]

    resp = http_client.post("/api/v1/auth/switch-org", json={"org_id": org_id}, headers=headers)
    assert resp.status_code == 200, resp.text

    # Confirm workspace is active before disabling membership
    resp = http_client.get("/api/v1/auth/me")
    assert resp.status_code == 200
    assert resp.json().get("org_id") == org_id

    # Disable the membership via shared DB session
    user = db_session.query(User).filter(User.email == email).first()
    assert user is not None
    membership = (
        db_session.query(Membership)
        .filter(Membership.user_id == user.id, Membership.org_id == org_id)
        .first()
    )
    assert membership is not None
    membership.is_active = False
    db_session.flush()

    # Refresh should succeed (not rejected)
    csrf_token = http_client.cookies.get("es_csrf")
    resp = http_client.post("/api/v1/auth/refresh", headers={"X-CSRF-Token": csrf_token})
    assert resp.status_code == 200, (
        f"Expected 200 on refresh with disabled membership, got {resp.status_code}: {resp.text}"
    )

    # After rotation, /auth/me must show no workspace context
    resp = http_client.get("/api/v1/auth/me")
    assert resp.status_code == 200
    me = resp.json()
    assert me.get("org_id") in ("", None), (
        f"Expected empty org_id after disabled-membership refresh, got: {me.get('org_id')!r}"
    )


# ── 5. Expired family cannot refresh ─────────────────────────────────────────


def test_expired_family_cannot_refresh(
    http_client: TestClient, fake_email, db_session: SASession
) -> None:
    """Setting family_expires_at in the past immediately blocks token refresh."""
    email = "expired_family_refresh@example.com"
    register_and_verify(http_client, fake_email, email)
    login(http_client, email)

    refresh_token = http_client.cookies.get("es_refresh")
    csrf_token = http_client.cookies.get("es_csrf")
    assert refresh_token, "No es_refresh cookie after login"
    assert csrf_token, "No es_csrf cookie after login"

    # Find the active session and expire the family via shared DB session
    user = db_session.query(User).filter(User.email == email).first()
    assert user is not None
    session = (
        db_session.query(AuthSession)
        .filter(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
        .first()
    )
    assert session is not None
    session.family_expires_at = datetime.now(tz=UTC) - timedelta(hours=1)
    db_session.flush()

    resp = http_client.post("/api/v1/auth/refresh", headers={"X-CSRF-Token": csrf_token})
    assert resp.status_code == 401
    body = resp.json()
    error = body.get("detail", {}).get("error") or body.get("error")
    assert error == "SESSION_EXPIRED", f"Expected SESSION_EXPIRED, got: {error!r} — body: {body}"
