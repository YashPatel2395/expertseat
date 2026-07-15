"""Integration tests for optional workspace context (null, not empty strings).

Invariants verified:
  1. No-membership login returns org_id=null in /auth/me
  2. Disabled-membership login returns org_id=null
  3. Login with active membership returns org_id as a non-null string
  4. Refresh with no-workspace session returns org_id=null
  5. create_access_token rejects empty-string org_id
  6. create_access_token rejects mismatched presence (org without mid)
  7. org_id=null does not break workspace-gated endpoints (still 403)
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session as SASession

from app.models.organization import Membership
from app.models.user import User
from tests.integration.conftest import csrf_headers, login, register_and_verify

pytestmark = pytest.mark.integration

_PASSWORD = "TestPassword123!"


# ── 1. No membership → org_id is null ─────────────────────────────────────────


def test_no_membership_returns_null_org_id(
    http_client: TestClient, fake_email, db_session: SASession
):
    email = "optws1@example.com"
    register_and_verify(http_client, fake_email, email, password=_PASSWORD)

    # Remove all memberships before login
    user = db_session.query(User).filter(User.email == email).first()
    assert user is not None
    db_session.query(Membership).filter(Membership.user_id == user.id).delete()
    db_session.flush()

    login(http_client, email, password=_PASSWORD)

    resp = http_client.get("/api/v1/auth/me")
    assert resp.status_code == 200
    body = resp.json()
    assert body["org_id"] is None, (
        f"Expected org_id=null for no-membership session, got {body['org_id']!r}"
    )
    assert body["role"] == "", f"Expected role='' for no-membership session, got {body['role']!r}"


# ── 2. Disabled membership → org_id is null ────────────────────────────────────


def test_disabled_membership_returns_null_org_id(
    http_client: TestClient, fake_email, db_session: SASession
):
    email = "optws2@example.com"
    register_and_verify(http_client, fake_email, email, password=_PASSWORD)

    user = db_session.query(User).filter(User.email == email).first()
    assert user is not None
    db_session.query(Membership).filter(Membership.user_id == user.id).update({"is_active": False})
    db_session.flush()

    login(http_client, email, password=_PASSWORD)

    resp = http_client.get("/api/v1/auth/me")
    assert resp.status_code == 200
    body = resp.json()
    assert body["org_id"] is None, (
        f"Expected org_id=null for disabled-membership session, got {body['org_id']!r}"
    )


# ── 3. Active membership → org_id is a non-null string ────────────────────────


def test_active_membership_returns_non_null_org_id(
    http_client: TestClient, fake_email, db_session: SASession
):
    email = "optws3@example.com"
    register_and_verify(http_client, fake_email, email, password=_PASSWORD)
    login(http_client, email, password=_PASSWORD)

    resp = http_client.get("/api/v1/auth/me")
    assert resp.status_code == 200
    body = resp.json()
    assert body["org_id"] is not None, "Expected org_id to be non-null with active membership"
    assert isinstance(body["org_id"], str), f"org_id must be a string, got {type(body['org_id'])}"
    assert body["org_id"] != "", "org_id must not be empty string"


# ── 4. Refresh with no-workspace session preserves null org_id ────────────────


def test_refresh_no_workspace_session_preserves_null(
    http_client: TestClient, fake_email, db_session: SASession
):
    email = "optws4@example.com"
    register_and_verify(http_client, fake_email, email, password=_PASSWORD)

    user = db_session.query(User).filter(User.email == email).first()
    assert user is not None
    db_session.query(Membership).filter(Membership.user_id == user.id).delete()
    db_session.flush()

    login(http_client, email, password=_PASSWORD)

    resp = http_client.post("/api/v1/auth/refresh", headers=csrf_headers(http_client))
    assert resp.status_code == 200, resp.text

    resp = http_client.get("/api/v1/auth/me")
    assert resp.status_code == 200
    body = resp.json()
    assert body["org_id"] is None, (
        f"Expected org_id=null after refresh with no-workspace session, got {body['org_id']!r}"
    )


# ── 5. create_access_token rejects empty-string org_id ────────────────────────


def test_create_access_token_rejects_empty_string_org_id():
    from app.auth.tokens import create_access_token

    with pytest.raises(ValueError, match="empty string"):
        create_access_token(
            user_id="user-1",
            session_id="sess-1",
            org_id="",  # must be rejected
            membership_id=None,
            role="",
            jti="jti-1",
        )


# ── 6. create_access_token rejects mismatched presence ────────────────────────


def test_create_access_token_rejects_mismatched_presence():
    from app.auth.tokens import create_access_token

    with pytest.raises(ValueError, match="mismatched"):
        create_access_token(
            user_id="user-1",
            session_id="sess-1",
            org_id="org-123",  # org set but mid is None
            membership_id=None,
            role="admin",
            jti="jti-1",
        )


# ── 7. null org_id → workspace endpoints return 403, not 500 ──────────────────


def test_null_org_id_gives_403_on_workspace_endpoint(
    http_client: TestClient, fake_email, db_session: SASession
):
    email = "optws7@example.com"
    register_and_verify(http_client, fake_email, email, password=_PASSWORD)

    user = db_session.query(User).filter(User.email == email).first()
    assert user is not None
    db_session.query(Membership).filter(Membership.user_id == user.id).delete()
    db_session.flush()

    login(http_client, email, password=_PASSWORD)

    # Workspace-scoped endpoint should return 403 NO_ACTIVE_WORKSPACE
    resp = http_client.get("/api/v1/workspace/members")
    assert resp.status_code == 403, (
        f"Expected 403 for no-workspace session on workspace endpoint, "
        f"got {resp.status_code}: {resp.text}"
    )
    error = resp.json().get("detail", {}).get("error")
    assert error == "NO_ACTIVE_WORKSPACE", f"Expected NO_ACTIVE_WORKSPACE, got {error!r}"
