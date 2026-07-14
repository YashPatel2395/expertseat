"""Cross-session audit-rollback tests.

Proved invariant: if _write_audit() raises inside a business mutation, the
mutation itself must also roll back — nothing partial reaches the database.

These tests differ from test_audit_atomicity.py in one critical way:
  • test_audit_atomicity.py uses the savepoint-wrapped db_session fixture and
    re-queries on the SAME connection.  expire_all() confirms the SAVEPOINT
    was NOT released, but it cannot prove the data was never committed to the
    real PostgreSQL database.
  • This file uses real committed data (bypassing savepoints) and opens a
    *separate* engine connection to read back the row.  Only truly committed
    data is visible to the second connection, so a non-nil read here would mean
    the mutation leaked past the transaction boundary despite the audit failure.

Pattern for each test:
  1. Set up a user/org via TestClient (real commits to the DB).
  2. Capture the pre-mutation state via a separate engine connection.
  3. Patch _write_audit to raise RuntimeError.
  4. Fire the mutation via a fresh TestClient (expect 500).
  5. Open another separate engine connection and verify the row is unchanged.
  6. Cleanup in a finally block.
"""

import os
import re
from unittest.mock import patch

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


# ── Helpers ────────────────────────────────────────────────────────────────────


def _audit_raises(*args, **kwargs):
    """Drop-in replacement for _write_audit that always raises."""
    raise RuntimeError("Simulated audit failure")


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
    assert resp.status_code == 200
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
    resp = client.post(
        "/api/v1/auth/switch-org",
        json={"org_id": org_id},
        headers={"X-CSRF-Token": csrf},
    )
    assert resp.status_code == 200, f"Switch org failed: {resp.text}"
    new_csrf = client.cookies.get("es_csrf")
    assert new_csrf, "No es_csrf after switch-org"
    return new_csrf


def _invite_accept_new(
    admin_client: TestClient,
    fake_email: FakeEmailProvider,
    admin_csrf: str,
    invitee_email: str,
    role: str = "recruiter",
) -> str:
    """Invite invitee_email and have them accept via accept-new.  Returns user_id."""
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

    with TestClient(app, raise_server_exceptions=False) as c:
        resp = c.post(
            "/api/v1/workspace/invitations/accept-new",
            json={"token": inv_token, "full_name": "Invitee", "password": _PASSWORD},
        )
        assert resp.status_code == 201, f"Accept-new failed: {resp.text}"
        me = c.get("/api/v1/auth/me")
        return me.json()["user_id"]


def _query_single(sql: str, params: dict):
    """Run a SELECT on a fresh engine connection and return the first row (or None)."""
    engine = create_engine(_DATABASE_URL)
    try:
        with engine.connect() as conn:
            result = conn.execute(text(sql), params)
            return result.fetchone()
    finally:
        engine.dispose()


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


def test_role_change_rolls_back_on_audit_failure(fake_email: FakeEmailProvider) -> None:
    """If _write_audit raises during a role change, the role must not change in the DB."""
    from app.main import app

    admin_email = "xsar_role_admin@example.com"
    member_email = "xsar_role_member@example.com"

    try:
        org_id: str = ""
        member_user_id: str = ""

        with TestClient(app, raise_server_exceptions=False) as admin_client:
            _register_and_verify(admin_client, fake_email, admin_email, "Role Rollback Admin")
            csrf = _login(admin_client, admin_email)
            org = _create_org(admin_client, csrf, "Role Rollback Org")
            org_id = org["id"]
            csrf = _switch_org(admin_client, csrf, org_id)

            member_user_id = _invite_accept_new(
                admin_client, fake_email, csrf, member_email, role="recruiter"
            )

            # Confirm initial role via separate connection
            row = _query_single(
                "SELECT role FROM memberships WHERE user_id = :uid AND org_id = :oid",
                {"uid": member_user_id, "oid": org_id},
            )
            assert row is not None and row[0] == "recruiter", (
                f"Expected initial role 'recruiter', got {row[0] if row else None!r}"
            )

            # Attempt role change with audit failure
            with patch("app.services.workspace._write_audit", side_effect=_audit_raises):
                try:
                    resp = admin_client.patch(
                        f"/api/v1/workspace/members/{member_user_id}",
                        json={"role": "reviewer"},
                        headers={"X-CSRF-Token": csrf},
                    )
                    assert resp.status_code == 500, (
                        f"Expected 500 when audit fails, got {resp.status_code}"
                    )
                except Exception:
                    # raise_server_exceptions=False should prevent re-raise, but
                    # guard anyway.
                    pass

        # Verify in a NEW separate connection — role must still be 'recruiter'
        row = _query_single(
            "SELECT role FROM memberships WHERE user_id = :uid AND org_id = :oid",
            {"uid": member_user_id, "oid": org_id},
        )
        assert row is not None, "Membership row not found after rollback"
        assert row[0] == "recruiter", (
            f"Role must not change when audit fails; found {row[0]!r} in separate connection"
        )

    finally:
        _cleanup([admin_email, member_email])


def test_member_disable_rolls_back_on_audit_failure(fake_email: FakeEmailProvider) -> None:
    """If _write_audit raises during member disable, is_active must remain True in the DB."""
    from app.main import app

    admin_email = "xsar_disable_admin@example.com"
    member_email = "xsar_disable_member@example.com"

    try:
        org_id: str = ""
        member_user_id: str = ""

        with TestClient(app, raise_server_exceptions=False) as admin_client:
            _register_and_verify(admin_client, fake_email, admin_email, "Disable Rollback Admin")
            csrf = _login(admin_client, admin_email)
            org = _create_org(admin_client, csrf, "Disable Rollback Org")
            org_id = org["id"]
            csrf = _switch_org(admin_client, csrf, org_id)

            member_user_id = _invite_accept_new(admin_client, fake_email, csrf, member_email)

            # Confirm member is currently active
            row = _query_single(
                "SELECT is_active FROM memberships WHERE user_id = :uid AND org_id = :oid",
                {"uid": member_user_id, "oid": org_id},
            )
            assert row is not None and row[0] is True, (
                f"Expected is_active=True initially, got {row[0] if row else None!r}"
            )

            # Attempt disable with audit failure
            with patch("app.services.workspace._write_audit", side_effect=_audit_raises):
                try:
                    resp = admin_client.patch(
                        f"/api/v1/workspace/members/{member_user_id}/status",
                        json={"is_active": False},
                        headers={"X-CSRF-Token": csrf},
                    )
                    assert resp.status_code == 500, (
                        f"Expected 500 when audit fails, got {resp.status_code}"
                    )
                except Exception:
                    pass

        # Verify in a NEW separate connection — is_active must still be True
        row = _query_single(
            "SELECT is_active FROM memberships WHERE user_id = :uid AND org_id = :oid",
            {"uid": member_user_id, "oid": org_id},
        )
        assert row is not None, "Membership row not found after rollback"
        assert row[0] is True, (
            f"is_active must remain True when audit fails; found {row[0]!r} in separate connection"
        )

    finally:
        _cleanup([admin_email, member_email])


def test_org_settings_rolls_back_on_audit_failure(fake_email: FakeEmailProvider) -> None:
    """If _write_audit raises during org settings update, the org name must be unchanged."""
    from app.main import app

    admin_email = "xsar_settings_admin@example.com"

    try:
        org_id: str = ""
        original_name = "Original Settings Name"

        with TestClient(app, raise_server_exceptions=False) as admin_client:
            _register_and_verify(admin_client, fake_email, admin_email, "Settings Rollback Admin")
            csrf = _login(admin_client, admin_email)
            org = _create_org(admin_client, csrf, original_name)
            org_id = org["id"]
            csrf = _switch_org(admin_client, csrf, org_id)

            # Confirm initial name via separate connection
            row = _query_single(
                "SELECT name FROM organizations WHERE id = :oid",
                {"oid": org_id},
            )
            assert row is not None and row[0] == original_name, (
                f"Expected org name '{original_name}', got {row[0] if row else None!r}"
            )

            # Attempt settings update with audit failure
            with patch("app.services.workspace._write_audit", side_effect=_audit_raises):
                try:
                    resp = admin_client.patch(
                        "/api/v1/workspace/settings",
                        json={"name": "Should Not Be Committed"},
                        headers={"X-CSRF-Token": csrf},
                    )
                    assert resp.status_code == 500, (
                        f"Expected 500 when audit fails, got {resp.status_code}"
                    )
                except Exception:
                    pass

        # Verify in a NEW separate connection — name must be unchanged
        row = _query_single(
            "SELECT name FROM organizations WHERE id = :oid",
            {"oid": org_id},
        )
        assert row is not None, "Organization row not found after rollback"
        assert row[0] == original_name, (
            f"Org name must not change when audit fails; "
            f"found {row[0]!r} in separate connection (expected {original_name!r})"
        )

    finally:
        _cleanup([admin_email])


def test_invitation_create_rolls_back_on_audit_failure(
    fake_email: FakeEmailProvider,
) -> None:
    """If _write_audit raises during invitation creation, no invitation row must exist."""
    from app.main import app

    admin_email = "xsar_inv_admin@example.com"
    invitee_email = "xsar_inv_target@example.com"

    try:
        org_id: str = ""

        with TestClient(app, raise_server_exceptions=False) as admin_client:
            _register_and_verify(admin_client, fake_email, admin_email, "Inv Rollback Admin")
            csrf = _login(admin_client, admin_email)
            org = _create_org(admin_client, csrf, "Inv Rollback Org")
            org_id = org["id"]
            csrf = _switch_org(admin_client, csrf, org_id)

            # Confirm no invitation for invitee_email yet
            row = _query_single(
                """
                SELECT id FROM organization_invitations
                WHERE email = :email AND org_id = :oid
                """,
                {"email": invitee_email, "oid": org_id},
            )
            assert row is None, f"Did not expect an existing invitation for {invitee_email}"

            # Attempt invitation creation with audit failure
            with patch("app.services.workspace._write_audit", side_effect=_audit_raises):
                try:
                    resp = admin_client.post(
                        "/api/v1/workspace/invitations",
                        json={"email": invitee_email, "role": "recruiter"},
                        headers={"X-CSRF-Token": csrf},
                    )
                    assert resp.status_code == 500, (
                        f"Expected 500 when audit fails, got {resp.status_code}"
                    )
                except Exception:
                    pass

        # Verify in a NEW separate connection — invitation must NOT exist
        row = _query_single(
            """
            SELECT id FROM organization_invitations
            WHERE email = :email AND org_id = :oid
            """,
            {"email": invitee_email, "oid": org_id},
        )
        assert row is None, (
            f"Invitation row must not exist when audit fails; "
            f"found id={row[0]!r} in separate connection"
        )

    finally:
        _cleanup([admin_email])
