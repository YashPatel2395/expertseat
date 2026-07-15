"""Registration atomicity and invariant tests.

Proves:
  1. POST /auth/register creates exactly one user.
  2. It creates exactly one organization.
  3. It creates exactly one Admin membership.
  4. User, organization, membership, and token are committed atomically.
  5. Duplicate email does not create an orphan organization.
  6. Verified self-registering user logs in with active org context.
  7. Default workspace name is derived from the registrant's name.
  8. The JWT immediately after login carries org_id and admin role.
  9. Verification activates the correct user, leaving other users unaffected.
 10. Slug collisions for the default workspace are resolved without partial records.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session as SASession

from app.models.organization import Membership, Organization
from app.models.user import EmailVerificationToken, User
from tests.integration.conftest import login, register_and_verify

pytestmark = pytest.mark.integration


# ── 1. Exactly one user created ────────────────────────────────────────────────


def test_register_creates_exactly_one_user(
    http_client: TestClient, fake_email, db_session: SASession
):
    before = db_session.query(User).count()
    register_and_verify(http_client, fake_email, "inv1@example.com")
    after = db_session.query(User).count()
    assert after - before == 1


# ── 2. Exactly one organization created ───────────────────────────────────────


def test_register_creates_exactly_one_organization(
    http_client: TestClient, fake_email, db_session: SASession
):
    before = db_session.query(Organization).count()
    register_and_verify(http_client, fake_email, "inv2@example.com")
    after = db_session.query(Organization).count()
    assert after - before == 1


# ── 3. Exactly one admin membership created ────────────────────────────────────


def test_register_creates_exactly_one_admin_membership(
    http_client: TestClient, fake_email, db_session: SASession
):
    before = db_session.query(Membership).filter(Membership.role == "admin").count()
    register_and_verify(http_client, fake_email, "inv3@example.com")
    after = db_session.query(Membership).filter(Membership.role == "admin").count()
    assert after - before == 1


# ── 4. Atomicity: all three records (user, org, membership) appear together ────


def test_register_creates_user_org_membership_atomically(
    http_client: TestClient, fake_email, db_session: SASession
):
    resp = http_client.post(
        "/api/v1/auth/register",
        json={"email": "atomic@example.com", "password": "Password123!", "full_name": "Atomic"},
    )
    assert resp.status_code == 201

    user = db_session.query(User).filter(User.email == "atomic@example.com").first()
    assert user is not None

    memberships = db_session.query(Membership).filter(Membership.user_id == user.id).all()
    assert len(memberships) == 1
    m = memberships[0]
    assert m.role == "admin"
    assert m.is_active is True

    org = db_session.query(Organization).filter(Organization.id == m.org_id).first()
    assert org is not None
    assert org.slug  # slug was generated

    token = (
        db_session.query(EmailVerificationToken)
        .filter(EmailVerificationToken.user_id == user.id)
        .first()
    )
    assert token is not None


# ── 5. Duplicate email leaves no orphan organization ──────────────────────────


def test_duplicate_email_does_not_create_orphan_org(
    http_client: TestClient, fake_email, db_session: SASession
):
    # First registration succeeds
    register_and_verify(http_client, fake_email, "dup@example.com")
    org_count_after_first = db_session.query(Organization).count()

    # Second registration with the same email must fail
    resp = http_client.post(
        "/api/v1/auth/register",
        json={"email": "dup@example.com", "password": "Password123!", "full_name": "Dup"},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["error"] == "EMAIL_ALREADY_EXISTS"

    # No extra organization must have been created
    assert db_session.query(Organization).count() == org_count_after_first


# ── 6. Verified user logs in with active org context ─────────────────────────


def test_verified_user_logs_in_with_org_context(http_client: TestClient, fake_email):
    register_and_verify(http_client, fake_email, "ctx@example.com")
    login(http_client, "ctx@example.com")

    resp = http_client.get("/api/v1/auth/me")
    assert resp.status_code == 200
    data = resp.json()
    assert data["org_id"], "org_id must be populated after login"
    assert data["role"] == "admin"


# ── 7. Default workspace name is derived from full_name ───────────────────────


def test_default_workspace_name_derived_from_full_name(
    http_client: TestClient, fake_email, db_session: SASession
):
    register_and_verify(http_client, fake_email, "named@example.com", full_name="Alice Wonderland")
    user = db_session.query(User).filter(User.email == "named@example.com").first()
    assert user is not None
    membership = db_session.query(Membership).filter(Membership.user_id == user.id).first()
    assert membership is not None
    org = db_session.query(Organization).filter(Organization.id == membership.org_id).first()
    assert org is not None
    assert "Alice Wonderland" in org.name


# ── 8. JWT after first login carries org_id and admin role ────────────────────


def test_jwt_after_login_carries_workspace_claims(http_client: TestClient, fake_email):
    register_and_verify(http_client, fake_email, "jwt@example.com")
    login(http_client, "jwt@example.com")

    # Access token delivered via HttpOnly cookie only — verify via /me
    assert http_client.cookies.get("es_access"), "es_access cookie must be set after login"

    me = http_client.get("/api/v1/auth/me")
    assert me.status_code == 200
    data = me.json()
    assert data["org_id"]
    assert data["role"] == "admin"
    assert data["user_id"]
    assert data["session_id"]


# ── 9. Verification activates the correct user only ───────────────────────────


def test_verification_activates_correct_user(
    http_client: TestClient, fake_email, db_session: SASession
):
    # Register two users — verify only the first
    register_and_verify(http_client, fake_email, "first@example.com")
    # Register second without verifying
    http_client.post(
        "/api/v1/auth/register",
        json={"email": "second@example.com", "password": "Password123!", "full_name": "Second"},
    )

    first = db_session.query(User).filter(User.email == "first@example.com").first()
    second = db_session.query(User).filter(User.email == "second@example.com").first()
    assert first is not None and first.email_verified is True
    assert second is not None and second.email_verified is False


# ── 10. Slug collision resolved without partial records ────────────────────────


def test_slug_collision_resolved_cleanly(
    http_client: TestClient, fake_email, db_session: SASession
):
    # Both users have the same full_name → same base slug → collision handling
    register_and_verify(http_client, fake_email, "slug1@example.com", full_name="Common Name")
    register_and_verify(http_client, fake_email, "slug2@example.com", full_name="Common Name")

    orgs = (
        db_session.query(Organization).filter(Organization.name == "Common Name's Workspace").all()
    )
    assert len(orgs) == 2, "Both orgs must exist"
    slugs = {o.slug for o in orgs}
    assert len(slugs) == 2, "Slugs must be unique even when names collide"
