"""Integration tests for DB-backed authorization.

These tests verify that the auth dependency re-validates every request
against live DB state — revocation, expiry, user status, membership status,
and role changes all take effect immediately without requiring token re-issue.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session as SASession

from app.models.organization import Membership
from app.models.session import AuthSession
from app.models.user import User
from tests.integration.conftest import csrf_headers, login, register_and_verify

pytestmark = pytest.mark.integration


def test_revoked_session_returns_401(http_client: TestClient, fake_email, db_session: SASession):
    """Revoking an AuthSession row immediately blocks subsequent requests."""
    email = "revoked@example.com"
    register_and_verify(http_client, fake_email, email)
    login(http_client, email)

    user = db_session.query(User).filter(User.email == email).first()
    assert user is not None
    session = (
        db_session.query(AuthSession)
        .filter(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
        .first()
    )
    assert session is not None

    session.revoked_at = datetime.now(tz=UTC)
    db_session.flush()

    resp = http_client.get("/api/v1/auth/me")
    assert resp.status_code == 401
    assert resp.json()["detail"]["error"] == "SESSION_INVALID"


def test_expired_session_returns_401(http_client: TestClient, fake_email, db_session: SASession):
    """Setting session.expires_at in the past immediately blocks access."""
    email = "expired_session@example.com"
    register_and_verify(http_client, fake_email, email)
    login(http_client, email)

    user = db_session.query(User).filter(User.email == email).first()
    assert user is not None
    session = (
        db_session.query(AuthSession)
        .filter(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
        .first()
    )
    assert session is not None

    session.expires_at = datetime.now(tz=UTC) - timedelta(hours=1)
    db_session.flush()

    resp = http_client.get("/api/v1/auth/me")
    assert resp.status_code == 401


def test_disabled_user_returns_401(http_client: TestClient, fake_email, db_session: SASession):
    """Disabling a user account immediately blocks their active sessions."""
    email = "disabled_user@example.com"
    register_and_verify(http_client, fake_email, email)
    login(http_client, email)

    user = db_session.query(User).filter(User.email == email).first()
    assert user is not None

    user.is_active = False
    db_session.flush()

    resp = http_client.get("/api/v1/auth/me")
    assert resp.status_code == 401
    assert resp.json()["detail"]["error"] == "ACCOUNT_INVALID"


def test_unverified_user_cannot_access_protected_route(
    http_client: TestClient, fake_email, db_session: SASession
):
    """Revoking email verification after login immediately blocks access."""
    email = "unverified_me@example.com"

    # Register but don't verify — can't login yet
    http_client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "Password123!", "full_name": "Test User"},
    )

    # Bypass verification via DB to allow login
    user = db_session.query(User).filter(User.email == email).first()
    assert user is not None
    user.email_verified = True
    db_session.flush()

    login(http_client, email)

    # Now revoke email verification — auth dep checks this on every request
    user.email_verified = False
    db_session.flush()

    resp = http_client.get("/api/v1/auth/me")
    assert resp.status_code == 401
    assert resp.json()["detail"]["error"] == "ACCOUNT_INVALID"


def test_disabled_membership_loses_workspace_access(
    http_client: TestClient, fake_email, db_session: SASession
):
    """Disabling a membership immediately blocks workspace-scoped endpoints."""
    email = "disabled_member@example.com"
    register_and_verify(http_client, fake_email, email)
    login(http_client, email)
    headers = csrf_headers(http_client)

    # Create an org and switch into it
    resp = http_client.post(
        "/api/v1/workspace/organizations",
        json={"name": "Membership Test Org"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    org = resp.json()

    http_client.post("/api/v1/auth/switch-org", json={"org_id": org["id"]}, headers=headers)

    # Confirm workspace access works before disabling
    resp = http_client.get("/api/v1/workspace/members")
    assert resp.status_code == 200

    # Disable the membership in the DB
    user = db_session.query(User).filter(User.email == email).first()
    assert user is not None
    membership = (
        db_session.query(Membership)
        .filter(Membership.user_id == user.id, Membership.org_id == org["id"])
        .first()
    )
    assert membership is not None
    membership.is_active = False
    db_session.flush()

    resp = http_client.get("/api/v1/workspace/members")
    assert resp.status_code == 403
    assert resp.json()["detail"]["error"] == "NO_ACTIVE_WORKSPACE"


def test_demoted_admin_role_effective_immediately(
    http_client: TestClient, fake_email, db_session: SASession
):
    """Changing membership.role in DB is reflected in the next /auth/me response."""
    email = "demoted_admin@example.com"
    register_and_verify(http_client, fake_email, email)
    login(http_client, email)
    headers = csrf_headers(http_client)

    resp = http_client.post(
        "/api/v1/workspace/organizations",
        json={"name": "Demotion Test Org"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    org = resp.json()

    http_client.post("/api/v1/auth/switch-org", json={"org_id": org["id"]}, headers=headers)

    # Confirm we are admin before the change
    resp = http_client.get("/api/v1/auth/me")
    assert resp.status_code == 200
    assert resp.json()["role"] == "admin"

    # Demote via DB
    user = db_session.query(User).filter(User.email == email).first()
    assert user is not None
    membership = (
        db_session.query(Membership)
        .filter(Membership.user_id == user.id, Membership.org_id == org["id"])
        .first()
    )
    assert membership is not None
    membership.role = "recruiter"
    db_session.flush()

    # Role change is effective immediately — JWT claim is ignored
    resp = http_client.get("/api/v1/auth/me")
    assert resp.status_code == 200
    assert resp.json()["role"] == "recruiter"


def test_fabricated_token_is_rejected(http_client: TestClient, fake_email, db_session: SASession):
    """A validly signed JWT with a non-existent session_id must be rejected."""
    from app.auth.tokens import create_access_token

    fake_session_id = str(uuid.uuid4())
    fake_user_id = str(uuid.uuid4())
    fake_org_id = str(uuid.uuid4())
    fake_membership_id = str(uuid.uuid4())
    fake_jti = str(uuid.uuid4())

    token = create_access_token(
        user_id=fake_user_id,
        session_id=fake_session_id,
        org_id=fake_org_id,
        membership_id=fake_membership_id,
        role="admin",
        jti=fake_jti,
    )

    # Inject the fabricated token directly into the client's cookie jar
    http_client.cookies.set("es_access", token)

    resp = http_client.get("/api/v1/auth/me")
    assert resp.status_code == 401
    assert resp.json()["detail"]["error"] == "SESSION_INVALID"
