"""Persistence tests.

Each test makes a mutation via the HTTP API, then calls db_session.expire_all()
to evict all ORM in-memory state, and finally re-queries the same session to
assert that the change is visible.

Because the conftest wraps every test in an outer transaction using
join_transaction_mode="create_savepoint", route-level db.commit() calls release
SAVEPOINTs.  expire_all() + a fresh query confirms the SAVEPOINT was released
(i.e. the data persisted within the transaction) rather than only flushed.
"""

import re

import pytest

from app.models.organization import Membership, Organization, OrganizationInvitation
from app.models.session import AuthSession
from app.models.user import User
from tests.integration.conftest import csrf_headers, login, register_and_verify

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_me(http_client) -> dict:
    resp = http_client.get("/api/v1/auth/me")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _create_org(http_client, name: str) -> dict:
    """Create an organisation and return its JSON payload."""
    hdrs = csrf_headers(http_client)
    resp = http_client.post(
        "/api/v1/workspace/organizations",
        json={"name": name},
        headers=hdrs,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _switch_org(http_client, org_id: str) -> None:
    resp = http_client.post(
        "/api/v1/auth/switch-org",
        json={"org_id": org_id},
        headers=csrf_headers(http_client),
    )
    assert resp.status_code == 200, resp.text


def _invite_and_join(http_client, fake_email, org_id: str, invitee_email: str) -> str:
    """Invite invitee_email to org_id, register them, accept the invite.

    Returns the invitee's user_id.  The http_client is left authenticated as
    the invitee at the end of this call.
    """
    hdrs = csrf_headers(http_client)
    inv_resp = http_client.post(
        "/api/v1/workspace/invitations",
        json={"email": invitee_email, "role": "recruiter"},
        headers=hdrs,
    )
    assert inv_resp.status_code == 201, inv_resp.text

    inv_email = fake_email.last_to(invitee_email)
    assert inv_email, f"No invitation email sent to {invitee_email}"
    match = re.search(r"/invite/([0-9a-f]{64})", inv_email.text_body)
    assert match, f"No invite token found in email body: {inv_email.text_body}"
    invite_token = match.group(1)

    register_and_verify(http_client, fake_email, invitee_email)
    login(http_client, invitee_email)
    accept_resp = http_client.post(
        "/api/v1/workspace/invitations/accept",
        json={"token": invite_token},
        headers=csrf_headers(http_client),
    )
    assert accept_resp.status_code == 200, accept_resp.text

    return _get_me(http_client)["user_id"]


def _setup_admin_with_member(http_client, fake_email, tag: str):
    """
    Register an admin, create a dedicated org, add a second member.

    Returns (admin_email, org_id, member_user_id).  The http_client is left
    authenticated as admin inside the new org.
    """
    admin_email = f"persist_{tag}_admin@example.com"
    admin_password = "Password123!"
    register_and_verify(http_client, fake_email, admin_email, admin_password)
    login(http_client, admin_email, admin_password)

    org = _create_org(http_client, f"Persist Org {tag}")
    org_id = org["id"]
    _switch_org(http_client, org_id)

    invitee_email = f"persist_{tag}_member@example.com"
    member_user_id = _invite_and_join(http_client, fake_email, org_id, invitee_email)

    # Return to admin context
    login(http_client, admin_email, admin_password)
    _switch_org(http_client, org_id)

    return admin_email, org_id, member_user_id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_role_change_persists(http_client, fake_email, db_session):
    """PATCH /workspace/members/{user_id} — role change survives expire_all."""
    _admin_email, org_id, member_user_id = _setup_admin_with_member(
        http_client, fake_email, "role_change"
    )

    resp = http_client.patch(
        f"/api/v1/workspace/members/{member_user_id}",
        json={"role": "reviewer"},
        headers=csrf_headers(http_client),
    )
    assert resp.status_code == 200, resp.text

    db_session.expire_all()

    membership = (
        db_session.query(Membership)
        .filter(Membership.user_id == member_user_id, Membership.org_id == org_id)
        .one()
    )
    assert membership.role == "reviewer", f"Expected 'reviewer', got '{membership.role}'"


def test_member_disable_persists(http_client, fake_email, db_session):
    """PATCH /workspace/members/{user_id}/status is_active=False survives expire_all."""
    _admin_email, org_id, member_user_id = _setup_admin_with_member(
        http_client, fake_email, "disable"
    )

    resp = http_client.patch(
        f"/api/v1/workspace/members/{member_user_id}/status",
        json={"is_active": False},
        headers=csrf_headers(http_client),
    )
    assert resp.status_code == 200, resp.text

    db_session.expire_all()

    membership = (
        db_session.query(Membership)
        .filter(Membership.user_id == member_user_id, Membership.org_id == org_id)
        .one()
    )
    assert membership.is_active is False, "Expected is_active=False after disable"


def test_member_reactivate_persists(http_client, fake_email, db_session):
    """Disable then reactivate — is_active=True survives expire_all."""
    _admin_email, org_id, member_user_id = _setup_admin_with_member(
        http_client, fake_email, "reactivate"
    )
    hdrs = csrf_headers(http_client)

    # First disable
    resp = http_client.patch(
        f"/api/v1/workspace/members/{member_user_id}/status",
        json={"is_active": False},
        headers=hdrs,
    )
    assert resp.status_code == 200, resp.text

    # Then reactivate
    resp = http_client.patch(
        f"/api/v1/workspace/members/{member_user_id}/status",
        json={"is_active": True},
        headers=csrf_headers(http_client),
    )
    assert resp.status_code == 200, resp.text

    db_session.expire_all()

    membership = (
        db_session.query(Membership)
        .filter(Membership.user_id == member_user_id, Membership.org_id == org_id)
        .one()
    )
    assert membership.is_active is True, "Expected is_active=True after reactivation"


def test_invitation_creation_persists(http_client, fake_email, db_session):
    """POST /workspace/invitations — invitation row survives expire_all."""
    email = "persist_inv_admin@example.com"
    register_and_verify(http_client, fake_email, email)
    login(http_client, email)
    org = _create_org(http_client, "Persist Inv Org")
    org_id = org["id"]
    _switch_org(http_client, org_id)

    target_email = "persist_inv_target@example.com"
    resp = http_client.post(
        "/api/v1/workspace/invitations",
        json={"email": target_email, "role": "recruiter"},
        headers=csrf_headers(http_client),
    )
    assert resp.status_code == 201, resp.text
    invitation_id = resp.json()["id"]

    db_session.expire_all()

    inv = (
        db_session.query(OrganizationInvitation)
        .filter(OrganizationInvitation.id == invitation_id)
        .first()
    )
    assert inv is not None, "Invitation not found after expire_all"
    assert inv.email == target_email
    assert inv.role == "recruiter"
    assert inv.org_id == org_id
    assert inv.revoked_at is None
    assert inv.accepted_at is None


def test_org_settings_update_persists(http_client, fake_email, db_session):
    """PATCH /workspace/settings — org name change survives expire_all."""
    email = "persist_settings_admin@example.com"
    register_and_verify(http_client, fake_email, email)
    login(http_client, email)
    org = _create_org(http_client, "Original Org Name")
    org_id = org["id"]
    _switch_org(http_client, org_id)

    resp = http_client.patch(
        "/api/v1/workspace/settings",
        json={"name": "Renamed Org Name"},
        headers=csrf_headers(http_client),
    )
    assert resp.status_code == 200, resp.text

    db_session.expire_all()

    organization = db_session.query(Organization).filter(Organization.id == org_id).one()
    assert organization.name == "Renamed Org Name", (
        f"Expected 'Renamed Org Name', got '{organization.name}'"
    )


def test_logout_revokes_session_persists(http_client, fake_email, db_session):
    """POST /auth/logout — AuthSession.revoked_at is set and survives expire_all."""
    email = "persist_logout@example.com"
    register_and_verify(http_client, fake_email, email)
    login(http_client, email)

    me = _get_me(http_client)
    session_id = me["session_id"]

    resp = http_client.post(
        "/api/v1/auth/logout",
        headers=csrf_headers(http_client),
    )
    assert resp.status_code == 200, resp.text

    db_session.expire_all()

    auth_session = db_session.query(AuthSession).filter(AuthSession.id == session_id).one()
    assert auth_session.revoked_at is not None, (
        "Expected revoked_at to be set after logout, but it is None"
    )


def test_password_reset_updates_user_persists(http_client, fake_email, db_session):
    """reset-password flow — User.password_changed_at is non-None after expire_all."""
    email = "persist_pwreset@example.com"
    register_and_verify(http_client, fake_email, email)

    # Trigger forgot-password to generate a reset token
    resp = http_client.post(
        "/api/v1/auth/forgot-password",
        json={"email": email},
    )
    assert resp.status_code == 200, resp.text

    # Extract reset token from the email
    reset_email = fake_email.last_to(email)
    assert reset_email, "No reset email received"
    match = re.search(r"/reset-password\?token=([0-9a-f]{64})", reset_email.text_body)
    assert match, f"No reset token found in email body: {reset_email.text_body}"
    reset_token = match.group(1)

    resp = http_client.post(
        "/api/v1/auth/reset-password",
        json={"token": reset_token, "new_password": "NewPassword456!"},
    )
    assert resp.status_code == 200, resp.text

    db_session.expire_all()

    user = db_session.query(User).filter(User.email == email).one()
    assert user.password_changed_at is not None, (
        "Expected password_changed_at to be set after reset, but it is None"
    )
