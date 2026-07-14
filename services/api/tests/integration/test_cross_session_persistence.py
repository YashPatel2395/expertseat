"""Cross-session persistence tests.

Each test:
  1. Sets up real committed data via TestClient (bypassing the savepoint wrapper).
  2. Makes an HTTP mutation via a TestClient.
  3. Opens a *separate* SQLAlchemy engine connection — a genuinely independent
     DB session — and re-reads the mutated row to confirm the change was
     durably committed to PostgreSQL.

WHY A SEPARATE CONNECTION IS REQUIRED
--------------------------------------
The standard db_session fixture wraps tests in a savepoint-based transaction.
expire_all() + re-query on the same connection merely confirms the SAVEPOINT was
released; it cannot prove the change survived a real commit.  A separate engine
connection with its own transaction can only see data that was truly committed by
PostgreSQL, so it provides the strongest possible durability guarantee.
"""

import os
import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.email.fake import FakeEmailProvider

pytestmark = pytest.mark.integration

_DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://expertseat:expertseat_dev@localhost:5432/expertseat",
)

_PASSWORD = "Password123!abc"


# ── Low-level helpers ──────────────────────────────────────────────────────────


def _register_and_verify(
    client: TestClient,
    fake_email: FakeEmailProvider,
    email: str,
    full_name: str = "Test User",
) -> None:
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": _PASSWORD, "full_name": full_name},
    )
    assert resp.status_code == 201, f"Register failed for {email}: {resp.text}"

    sent = fake_email.verification_message_for(email)
    assert sent is not None, f"No verification email for {email}"
    match = re.search(r"/verify-email\?token=([0-9a-f]{64})", sent.text_body)
    assert match, f"No verification token in email: {sent.text_body}"

    resp = client.post("/api/v1/auth/verify-email", json={"token": match.group(1)})
    assert resp.status_code == 200, f"Verify failed for {email}: {resp.text}"


def _login(client: TestClient, email: str) -> str:
    """Log in and return the CSRF token."""
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": _PASSWORD},
    )
    assert resp.status_code == 200, f"Login failed for {email}: {resp.text}"
    csrf = client.cookies.get("es_csrf")
    assert csrf, "No es_csrf cookie after login"
    return csrf


def _get_me(client: TestClient) -> dict:
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 200, f"/auth/me failed: {resp.text}"
    return resp.json()


def _create_org(client: TestClient, csrf: str, name: str) -> dict:
    resp = client.post(
        "/api/v1/workspace/organizations",
        json={"name": name},
        headers={"X-CSRF-Token": csrf},
    )
    assert resp.status_code == 201, f"Create org failed: {resp.text}"
    return resp.json()


def _switch_org(client: TestClient, csrf: str, org_id: str) -> str:
    """Switch to org and return the refreshed CSRF token."""
    resp = client.post(
        "/api/v1/auth/switch-org",
        json={"org_id": org_id},
        headers={"X-CSRF-Token": csrf},
    )
    assert resp.status_code == 200, f"Switch org failed: {resp.text}"
    new_csrf = client.cookies.get("es_csrf")
    assert new_csrf, "No es_csrf cookie after switch-org"
    return new_csrf


def _invite_accept_new(
    admin_client: TestClient,
    fake_email: FakeEmailProvider,
    admin_csrf: str,
    invitee_email: str,
    role: str = "recruiter",
) -> tuple[TestClient, str]:
    """Invite invitee_email and have them accept via accept-new.

    Returns (invitee_client, invitee_user_id).  The invitee_client is a live
    TestClient already authenticated as the invitee.
    """
    from app.main import app

    resp = admin_client.post(
        "/api/v1/workspace/invitations",
        json={"email": invitee_email, "role": role},
        headers={"X-CSRF-Token": admin_csrf},
    )
    assert resp.status_code == 201, f"Invite failed for {invitee_email}: {resp.text}"

    inv_msg = fake_email.invitation_message_for(invitee_email)
    assert inv_msg is not None, f"No invitation email for {invitee_email}"
    inv_match = re.search(r"invite/([0-9a-f]{64})", inv_msg.text_body)
    assert inv_match, f"No invite token in email: {inv_msg.text_body}"
    inv_token = inv_match.group(1)

    invitee_client = TestClient(app, raise_server_exceptions=False)
    resp = invitee_client.post(
        "/api/v1/workspace/invitations/accept-new",
        json={"token": inv_token, "full_name": "Invitee User", "password": _PASSWORD},
    )
    assert resp.status_code == 201, f"Accept-new failed for {invitee_email}: {resp.text}"

    me = invitee_client.get("/api/v1/auth/me")
    assert me.status_code == 200
    invitee_user_id = me.json()["user_id"]

    return invitee_client, invitee_user_id


def _cleanup(emails: list[str]) -> None:
    """Delete all orgs these users belong to, then the users themselves."""
    engine = create_engine(_DATABASE_URL)
    try:
        with engine.connect() as conn:
            for email in emails:
                conn.execute(
                    text("""
                        DELETE FROM organizations
                        WHERE id IN (
                            SELECT m.org_id FROM memberships m
                            JOIN users u ON u.id = m.user_id
                            WHERE u.email = :email
                        )
                    """),
                    {"email": email},
                )
            for email in emails:
                conn.execute(
                    text("DELETE FROM users WHERE email = :email"),
                    {"email": email},
                )
            conn.commit()
    finally:
        engine.dispose()


# ── Tests ──────────────────────────────────────────────────────────────────────


def test_role_change_persists(fake_email: FakeEmailProvider) -> None:
    """PATCH /workspace/members/{id} role change is visible in a separate DB connection."""
    from app.main import app

    admin_email = "xsp_role_admin@example.com"
    member_email = "xsp_role_member@example.com"

    try:
        with TestClient(app, raise_server_exceptions=False) as admin_client:
            _register_and_verify(admin_client, fake_email, admin_email, "Role Admin")
            csrf = _login(admin_client, admin_email)
            org = _create_org(admin_client, csrf, "Role Persist Org")
            org_id = org["id"]
            csrf = _switch_org(admin_client, csrf, org_id)

            _invitee_client, member_user_id = _invite_accept_new(
                admin_client, fake_email, csrf, member_email, role="recruiter"
            )

            resp = admin_client.patch(
                f"/api/v1/workspace/members/{member_user_id}",
                json={"role": "reviewer"},
                headers={"X-CSRF-Token": csrf},
            )
            assert resp.status_code == 200, f"Role change failed: {resp.text}"

        # Verify in a separate connection
        engine = create_engine(_DATABASE_URL)
        try:
            with engine.connect() as conn:
                result = conn.execute(
                    text("""
                        SELECT role FROM memberships
                        WHERE user_id = :uid AND org_id = :oid
                    """),
                    {"uid": member_user_id, "oid": org_id},
                )
                row = result.fetchone()
                assert row is not None, "Membership row not found in separate connection"
                assert row[0] == "reviewer", (
                    f"Expected role='reviewer' in separate connection, got {row[0]!r}"
                )
        finally:
            engine.dispose()

    finally:
        _cleanup([admin_email, member_email])


def test_member_disable_persists(fake_email: FakeEmailProvider) -> None:
    """PATCH /workspace/members/{id}/status is_active=False survives a new DB connection."""
    from app.main import app

    admin_email = "xsp_disable_admin@example.com"
    member_email = "xsp_disable_member@example.com"

    try:
        with TestClient(app, raise_server_exceptions=False) as admin_client:
            _register_and_verify(admin_client, fake_email, admin_email, "Disable Admin")
            csrf = _login(admin_client, admin_email)
            org = _create_org(admin_client, csrf, "Disable Persist Org")
            org_id = org["id"]
            csrf = _switch_org(admin_client, csrf, org_id)

            _invitee_client, member_user_id = _invite_accept_new(
                admin_client, fake_email, csrf, member_email
            )

            resp = admin_client.patch(
                f"/api/v1/workspace/members/{member_user_id}/status",
                json={"is_active": False},
                headers={"X-CSRF-Token": csrf},
            )
            assert resp.status_code == 200, f"Disable failed: {resp.text}"

        engine = create_engine(_DATABASE_URL)
        try:
            with engine.connect() as conn:
                result = conn.execute(
                    text("""
                        SELECT is_active FROM memberships
                        WHERE user_id = :uid AND org_id = :oid
                    """),
                    {"uid": member_user_id, "oid": org_id},
                )
                row = result.fetchone()
                assert row is not None, "Membership row not found"
                assert row[0] is False, (
                    f"Expected is_active=False in separate connection, got {row[0]!r}"
                )
        finally:
            engine.dispose()

    finally:
        _cleanup([admin_email, member_email])


def test_member_reactivate_persists(fake_email: FakeEmailProvider) -> None:
    """Disable then reactivate — is_active=True survives a new DB connection."""
    from app.main import app

    admin_email = "xsp_reactivate_admin@example.com"
    member_email = "xsp_reactivate_member@example.com"

    try:
        with TestClient(app, raise_server_exceptions=False) as admin_client:
            _register_and_verify(admin_client, fake_email, admin_email, "Reactivate Admin")
            csrf = _login(admin_client, admin_email)
            org = _create_org(admin_client, csrf, "Reactivate Persist Org")
            org_id = org["id"]
            csrf = _switch_org(admin_client, csrf, org_id)

            _invitee_client, member_user_id = _invite_accept_new(
                admin_client, fake_email, csrf, member_email
            )

            # Disable
            resp = admin_client.patch(
                f"/api/v1/workspace/members/{member_user_id}/status",
                json={"is_active": False},
                headers={"X-CSRF-Token": csrf},
            )
            assert resp.status_code == 200, f"Disable failed: {resp.text}"

            # Reactivate
            resp = admin_client.patch(
                f"/api/v1/workspace/members/{member_user_id}/status",
                json={"is_active": True},
                headers={"X-CSRF-Token": csrf},
            )
            assert resp.status_code == 200, f"Reactivate failed: {resp.text}"

        engine = create_engine(_DATABASE_URL)
        try:
            with engine.connect() as conn:
                result = conn.execute(
                    text("""
                        SELECT is_active FROM memberships
                        WHERE user_id = :uid AND org_id = :oid
                    """),
                    {"uid": member_user_id, "oid": org_id},
                )
                row = result.fetchone()
                assert row is not None, "Membership row not found"
                assert row[0] is True, f"Expected is_active=True after reactivation, got {row[0]!r}"
        finally:
            engine.dispose()

    finally:
        _cleanup([admin_email, member_email])


def test_org_settings_update_persists(fake_email: FakeEmailProvider) -> None:
    """PATCH /workspace/settings name change is visible in a separate DB connection."""
    from app.main import app

    admin_email = "xsp_settings_admin@example.com"

    try:
        with TestClient(app, raise_server_exceptions=False) as admin_client:
            _register_and_verify(admin_client, fake_email, admin_email, "Settings Admin")
            csrf = _login(admin_client, admin_email)
            org = _create_org(admin_client, csrf, "Original Org Name")
            org_id = org["id"]
            csrf = _switch_org(admin_client, csrf, org_id)

            resp = admin_client.patch(
                "/api/v1/workspace/settings",
                json={"name": "Renamed Via Separate Connection"},
                headers={"X-CSRF-Token": csrf},
            )
            assert resp.status_code == 200, f"Settings update failed: {resp.text}"

        engine = create_engine(_DATABASE_URL)
        try:
            with engine.connect() as conn:
                result = conn.execute(
                    text("SELECT name FROM organizations WHERE id = :oid"),
                    {"oid": org_id},
                )
                row = result.fetchone()
                assert row is not None, "Organization row not found"
                assert row[0] == "Renamed Via Separate Connection", (
                    f"Expected 'Renamed Via Separate Connection', got {row[0]!r}"
                )
        finally:
            engine.dispose()

    finally:
        _cleanup([admin_email])


def test_logout_session_revocation_persists(fake_email: FakeEmailProvider) -> None:
    """POST /auth/logout — session.revoked_at is non-NULL in a separate DB connection."""
    from app.main import app

    admin_email = "xsp_logout_admin@example.com"

    try:
        session_id: str = ""

        with TestClient(app, raise_server_exceptions=False) as admin_client:
            _register_and_verify(admin_client, fake_email, admin_email, "Logout Admin")
            csrf = _login(admin_client, admin_email)

            me = _get_me(admin_client)
            session_id = me["session_id"]

            resp = admin_client.post(
                "/api/v1/auth/logout",
                headers={"X-CSRF-Token": csrf},
            )
            assert resp.status_code == 200, f"Logout failed: {resp.text}"

        engine = create_engine(_DATABASE_URL)
        try:
            with engine.connect() as conn:
                result = conn.execute(
                    text("SELECT revoked_at FROM auth_sessions WHERE id = :sid"),
                    {"sid": session_id},
                )
                row = result.fetchone()
                assert row is not None, "AuthSession row not found"
                assert row[0] is not None, (
                    "Expected revoked_at to be set after logout, but it is NULL"
                )
        finally:
            engine.dispose()

    finally:
        _cleanup([admin_email])


def test_invitation_create_persists(fake_email: FakeEmailProvider) -> None:
    """POST /workspace/invitations — invitation row is visible in a separate DB connection."""
    from app.main import app

    admin_email = "xsp_inv_admin@example.com"
    invitee_email = "xsp_inv_target@example.com"

    try:
        invitation_id: str = ""
        org_id: str = ""

        with TestClient(app, raise_server_exceptions=False) as admin_client:
            _register_and_verify(admin_client, fake_email, admin_email, "Inv Admin")
            csrf = _login(admin_client, admin_email)
            org = _create_org(admin_client, csrf, "Inv Persist Org")
            org_id = org["id"]
            csrf = _switch_org(admin_client, csrf, org_id)

            resp = admin_client.post(
                "/api/v1/workspace/invitations",
                json={"email": invitee_email, "role": "recruiter"},
                headers={"X-CSRF-Token": csrf},
            )
            assert resp.status_code == 201, f"Invite failed: {resp.text}"
            invitation_id = resp.json()["id"]

        engine = create_engine(_DATABASE_URL)
        try:
            with engine.connect() as conn:
                result = conn.execute(
                    text("""
                        SELECT email, role, org_id, revoked_at, accepted_at
                        FROM organization_invitations
                        WHERE id = :iid
                    """),
                    {"iid": invitation_id},
                )
                row = result.fetchone()
                assert row is not None, "Invitation row not found in separate connection"
                assert row[0] == invitee_email, f"Unexpected email: {row[0]!r}"
                assert row[1] == "recruiter", f"Unexpected role: {row[1]!r}"
                assert str(row[2]) == org_id, f"Unexpected org_id: {row[2]!r}"
                assert row[3] is None, "revoked_at must be NULL for new invitation"
                assert row[4] is None, "accepted_at must be NULL for new invitation"
        finally:
            engine.dispose()

    finally:
        _cleanup([admin_email])


def test_password_change_persists(fake_email: FakeEmailProvider) -> None:
    """POST /auth/change-password — password_changed_at is non-NULL in separate connection."""
    from app.main import app

    admin_email = "xsp_pwchange_admin@example.com"
    new_password = "NewPassword456!xyz"

    try:
        user_id: str = ""

        with TestClient(app, raise_server_exceptions=False) as admin_client:
            _register_and_verify(admin_client, fake_email, admin_email, "PwChange Admin")
            csrf = _login(admin_client, admin_email)

            me = _get_me(admin_client)
            user_id = me["user_id"]

            resp = admin_client.post(
                "/api/v1/auth/change-password",
                json={
                    "current_password": _PASSWORD,
                    "new_password": new_password,
                },
                headers={"X-CSRF-Token": csrf},
            )
            assert resp.status_code == 200, f"Change-password failed: {resp.text}"

        engine = create_engine(_DATABASE_URL)
        try:
            with engine.connect() as conn:
                result = conn.execute(
                    text("SELECT password_changed_at FROM users WHERE id = :uid"),
                    {"uid": user_id},
                )
                row = result.fetchone()
                assert row is not None, "User row not found"
                assert row[0] is not None, (
                    "Expected password_changed_at to be set after password change, but it is NULL"
                )
        finally:
            engine.dispose()

    finally:
        _cleanup([admin_email])
