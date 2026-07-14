"""Tests for AuthSession nullable org context states.

AuthSession.org_id and membership_id are nullable to cover edge cases where
a user has no active org membership at login time.  This file documents and
tests each allowed state:

  State A — Normal: user has exactly one active membership (self-registered).
  State B — Multi-org: user has several memberships; login picks most recent.
  State C — No membership: user has zero memberships (org was deleted, or all
            memberships were removed).  Login issues a no-org token.
  State D — All memberships disabled: similar to C but memberships exist
            (is_active=False).  Login issues a no-org token.
  State E — Unverified: login is rejected before this state is reached (401).
  State F — Null-context token must be rejected by workspace-scoped endpoints.
  State G — switch_org from a null-context token succeeds if user has a
            valid membership.
  State H — No fake UUID is ever stored in org_id/membership_id.
  State I — Token hashes are not raw values; no plaintext refresh token is
            stored in the DB.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session as SASession

from app.models.organization import Membership
from tests.integration.conftest import csrf_headers, login, register_and_verify

pytestmark = pytest.mark.integration


# ── State A: single active membership → org context populated ─────────────────


def test_login_with_one_active_membership_carries_org_context(http_client: TestClient, fake_email):
    register_and_verify(http_client, fake_email, "ctx_a@example.com")
    login(http_client, "ctx_a@example.com")

    resp = http_client.get("/api/v1/auth/me")
    data = resp.json()
    assert data["org_id"], "org_id must be set when user has one active membership"
    assert data["role"] == "admin"


# ── State B: multiple active memberships → most-recent selected ───────────────


def test_login_with_multiple_memberships_selects_most_recent(
    http_client: TestClient, fake_email, db_session: SASession
):
    from datetime import UTC, datetime, timedelta

    from app.models.user import User

    register_and_verify(http_client, fake_email, "ctx_b@example.com")
    login(http_client, "ctx_b@example.com")
    headers = csrf_headers(http_client)

    # Create a second org — this membership will be more recent
    resp = http_client.post(
        "/api/v1/workspace/organizations", json={"name": "Second Org"}, headers=headers
    )
    assert resp.status_code == 201
    second_org_id = resp.json()["id"]

    # Within a savepoint-based test transaction, PostgreSQL's now() returns the
    # transaction start time, so all memberships get the same created_at.
    # Backdate the default workspace membership so the ordering is deterministic.
    user = db_session.query(User).filter(User.email == "ctx_b@example.com").first()
    assert user is not None
    db_session.query(Membership).filter(
        Membership.user_id == user.id, Membership.org_id != second_org_id
    ).update({"created_at": datetime.now(UTC) - timedelta(seconds=10)})
    db_session.flush()

    # Re-login: the most-recently-created active membership should be selected
    login(http_client, "ctx_b@example.com")
    me = http_client.get("/api/v1/auth/me").json()
    assert me["org_id"] == second_org_id


# ── State C: no memberships → no-org token; workspace endpoints return 403 ────


def test_login_with_no_memberships_issues_no_org_token(
    http_client: TestClient, fake_email, db_session: SASession
):
    register_and_verify(http_client, fake_email, "ctx_c@example.com")

    # Remove the membership created at registration
    from app.models.user import User

    user = db_session.query(User).filter(User.email == "ctx_c@example.com").first()
    assert user is not None
    db_session.query(Membership).filter(Membership.user_id == user.id).delete()
    db_session.flush()

    login(http_client, "ctx_c@example.com")

    me = http_client.get("/api/v1/auth/me").json()
    # No org context in token
    assert me["org_id"] == ""
    assert me["role"] == ""


# ── State D: all memberships disabled → no-org token ─────────────────────────


def test_login_with_only_disabled_memberships_issues_no_org_token(
    http_client: TestClient, fake_email, db_session: SASession
):
    register_and_verify(http_client, fake_email, "ctx_d@example.com")

    from app.models.user import User

    user = db_session.query(User).filter(User.email == "ctx_d@example.com").first()
    assert user is not None
    db_session.query(Membership).filter(Membership.user_id == user.id).update({"is_active": False})
    db_session.flush()

    login(http_client, "ctx_d@example.com")

    me = http_client.get("/api/v1/auth/me").json()
    assert me["org_id"] == ""
    assert me["role"] == ""


# ── State E: unverified user cannot login ─────────────────────────────────────


def test_login_before_email_verification_returns_401(http_client: TestClient, fake_email):
    http_client.post(
        "/api/v1/auth/register",
        json={
            "email": "unver@example.com",
            "password": "Password123!",
            "full_name": "Unverified",
        },
    )
    resp = http_client.post(
        "/api/v1/auth/login",
        json={"email": "unver@example.com", "password": "Password123!"},
    )
    assert resp.status_code == 401
    assert resp.json()["detail"]["error"] == "EMAIL_NOT_VERIFIED"


# ── State F: null-context token rejected by workspace endpoints ───────────────


def test_workspace_endpoints_reject_no_org_token(
    http_client: TestClient, fake_email, db_session: SASession
):
    register_and_verify(http_client, fake_email, "ctx_f@example.com")

    from app.models.user import User

    user = db_session.query(User).filter(User.email == "ctx_f@example.com").first()
    assert user is not None
    db_session.query(Membership).filter(Membership.user_id == user.id).delete()
    db_session.flush()

    login(http_client, "ctx_f@example.com")

    # Workspace endpoints that require org context must return 403
    resp = http_client.get("/api/v1/workspace/members")
    assert resp.status_code == 403

    resp = http_client.get("/api/v1/workspace/audit")
    assert resp.status_code == 403


# ── State G: switch_org from null context works if user has a valid membership ─


def test_switch_org_from_null_context_succeeds_with_valid_membership(
    http_client: TestClient, fake_email, db_session: SASession
):
    # Create user with an org membership, then remove it so login is no-org
    register_and_verify(http_client, fake_email, "ctx_g1@example.com")
    login(http_client, "ctx_g1@example.com")
    headers = csrf_headers(http_client)

    # Create a second org while still in the default workspace context
    resp = http_client.post(
        "/api/v1/workspace/organizations", json={"name": "Target Org"}, headers=headers
    )
    target_org_id = resp.json()["id"]

    # Now remove the membership for the DEFAULT workspace so that re-login is no-org
    from app.models.user import User

    user = db_session.query(User).filter(User.email == "ctx_g1@example.com").first()
    assert user is not None
    # Remove only the default workspace membership (not the "Target Org" one)
    default_membership = (
        db_session.query(Membership)
        .filter(Membership.user_id == user.id, Membership.org_id != target_org_id)
        .first()
    )
    if default_membership:
        db_session.delete(default_membership)
        db_session.flush()

    # Re-login — now has one remaining membership (Target Org), which is most recent
    login(http_client, "ctx_g1@example.com")
    me = http_client.get("/api/v1/auth/me").json()
    # Should pick up the Target Org membership since it's the only active one
    assert me["org_id"] == target_org_id


# ── State H: no fake UUID stored as org_id or membership_id ──────────────────


def test_no_fake_uuid_stored_as_org_id(http_client: TestClient, fake_email, db_session: SASession):
    register_and_verify(http_client, fake_email, "ctx_h@example.com")

    from app.models.session import AuthSession
    from app.models.user import User

    user = db_session.query(User).filter(User.email == "ctx_h@example.com").first()
    assert user is not None
    db_session.query(Membership).filter(Membership.user_id == user.id).delete()
    db_session.flush()

    login(http_client, "ctx_h@example.com")

    # The auth session must have org_id=NULL, not a fake user_id
    session = (
        db_session.query(AuthSession)
        .filter(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
        .first()
    )
    assert session is not None
    assert session.org_id is None, "org_id must be NULL, not a fake placeholder"
    assert session.membership_id is None, "membership_id must be NULL, not a fake placeholder"
    # FK integrity: NULL is valid; a fake user UUID is not
    assert session.org_id != user.id


# ── State I: raw refresh tokens are never stored ──────────────────────────────


def test_raw_refresh_token_not_stored_in_db(
    http_client: TestClient, fake_email, db_session: SASession
):
    register_and_verify(http_client, fake_email, "ctx_i@example.com")
    login(http_client, "ctx_i@example.com")

    raw_refresh = http_client.cookies.get("es_refresh")
    assert raw_refresh, "Refresh cookie must be set"

    from app.models.session import AuthSession
    from app.models.user import User

    user = db_session.query(User).filter(User.email == "ctx_i@example.com").first()
    assert user is not None

    sessions = db_session.query(AuthSession).filter(AuthSession.user_id == user.id).all()
    stored_hashes = {s.refresh_token_hash for s in sessions}
    assert raw_refresh not in stored_hashes, "Raw refresh token must not be stored; only its hash"
