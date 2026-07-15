"""Integration tests for invitation business rules.

Covers:
  - Blocking an invite to an existing active member (ALREADY_A_MEMBER)
  - Blocking a duplicate pending invitation (INVITATION_ALREADY_PENDING)
  - Rejecting acceptance of a revoked invitation
  - Single-use enforcement: second accept of same token is rejected
  - Email-mismatch: wrong user tries to accept another user's invitation
  - CSRF requirement on accept
  - Full happy-path: invited email registers, verifies, logs in, accepts
  - Role propagation: invite with role="admin" produces an admin membership
"""

import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session as SASession

from app.models.organization import Membership, OrganizationInvitation
from app.models.user import User
from tests.integration.conftest import csrf_headers, login, register_and_verify

pytestmark = pytest.mark.integration


# ── Setup helper ───────────────────────────────────────────────────────────────


def _setup_admin(
    http_client: TestClient,
    fake_email,
    email: str,
    org_name: str = "Invite Test Org",
) -> tuple[str, dict]:
    """Register + verify + login as an admin user who already has a default workspace.

    Registration automatically creates a personal workspace, so the user is
    immediately an admin.  We create an *additional* org so we can keep tests
    independent and control the org name.

    Returns (admin_email, headers_with_csrf).
    """
    register_and_verify(http_client, fake_email, email)
    login(http_client, email)
    headers = csrf_headers(http_client)

    resp = http_client.post(
        "/api/v1/workspace/organizations",
        json={"name": org_name},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    org = resp.json()

    # Switch context into the new org so subsequent workspace calls target it
    resp = http_client.post(
        "/api/v1/auth/switch-org",
        json={"org_id": org["id"]},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    headers = csrf_headers(http_client)

    return email, headers


def _extract_invite_token(fake_email, invited_email: str) -> str:
    """Pull the 64-char hex token out of the most recent invitation email."""
    inv_email = fake_email.invitation_message_for(invited_email)
    assert inv_email is not None, f"No invitation email found for {invited_email}"
    match = re.search(r"/invite/([0-9a-f]{64})", inv_email.text_body)
    assert match, f"No invite token found in email body:\n{inv_email.text_body}"
    return match.group(1)


# ── Test 1: existing active member cannot be invited ─────────────────────────


def test_existing_active_member_cannot_be_invited(
    http_client: TestClient, fake_email, db_session: SASession
) -> None:
    """Inviting an email that already belongs to an active member returns 409 ALREADY_A_MEMBER."""
    admin_email, headers = _setup_admin(
        http_client, fake_email, "inv1_admin@example.com", "Inv1 Org"
    )

    # The admin's own email is already an active member of the org they just switched into
    resp = http_client.post(
        "/api/v1/workspace/invitations",
        json={"email": admin_email, "role": "recruiter"},
        headers=headers,
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["error"] == "ALREADY_A_MEMBER"


# ── Test 2: duplicate pending invitation rejected ─────────────────────────────


def test_duplicate_pending_invitation_rejected(http_client: TestClient, fake_email) -> None:
    """Sending a second invitation to the same email returns 409 INVITATION_ALREADY_PENDING."""
    _setup_admin(http_client, fake_email, "inv2_admin@example.com", "Inv2 Org")
    headers = csrf_headers(http_client)

    first = http_client.post(
        "/api/v1/workspace/invitations",
        json={"email": "inv2_target@example.com", "role": "recruiter"},
        headers=headers,
    )
    assert first.status_code == 201, first.text

    second = http_client.post(
        "/api/v1/workspace/invitations",
        json={"email": "inv2_target@example.com", "role": "reviewer"},
        headers=headers,
    )
    assert second.status_code == 409, second.text
    assert second.json()["detail"]["error"] == "INVITATION_ALREADY_PENDING"


# ── Test 3: revoked invitation cannot be accepted ─────────────────────────────


def test_revoked_invitation_cannot_be_accepted(
    http_client: TestClient, fake_email, db_session: SASession
) -> None:
    """Accepting an invitation that has been revoked returns 400 or 401."""
    _setup_admin(http_client, fake_email, "inv3_admin@example.com", "Inv3 Org")
    headers = csrf_headers(http_client)

    invited_email = "inv3_target@example.com"
    resp = http_client.post(
        "/api/v1/workspace/invitations",
        json={"email": invited_email, "role": "recruiter"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    invitation_id = resp.json()["id"]

    # Grab the invite token before revoking (so we can still try to use it)
    invite_token = _extract_invite_token(fake_email, invited_email)

    # Revoke the invitation
    resp = http_client.delete(
        f"/api/v1/workspace/invitations/{invitation_id}",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text

    # Register and log in as the invited user
    register_and_verify(http_client, fake_email, invited_email)
    login(http_client, invited_email)

    # Attempt to accept the (now-revoked) invitation
    resp = http_client.post(
        "/api/v1/workspace/invitations/accept",
        json={"token": invite_token},
        headers=csrf_headers(http_client),
    )
    assert resp.status_code in (400, 401), (
        f"Expected 400 or 401 for revoked invite, got {resp.status_code}: {resp.text}"
    )


# ── Test 4: invitation is single-use ─────────────────────────────────────────


def test_invitation_is_single_use(
    http_client: TestClient, fake_email, db_session: SASession
) -> None:
    """Accepting an already-accepted invitation token a second time fails."""
    _setup_admin(http_client, fake_email, "inv4_admin@example.com", "Inv4 Org")
    headers = csrf_headers(http_client)

    invited_email = "inv4_target@example.com"
    resp = http_client.post(
        "/api/v1/workspace/invitations",
        json={"email": invited_email, "role": "recruiter"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text

    # Capture invite token before registering (registration email may push it out)
    invite_token = _extract_invite_token(fake_email, invited_email)

    # Register, verify and log in as the invited user
    register_and_verify(http_client, fake_email, invited_email)
    login(http_client, invited_email)

    # First accept — should succeed
    first_accept = http_client.post(
        "/api/v1/workspace/invitations/accept",
        json={"token": invite_token},
        headers=csrf_headers(http_client),
    )
    assert first_accept.status_code == 200, first_accept.text

    # Second accept with the same token — must fail
    second_accept = http_client.post(
        "/api/v1/workspace/invitations/accept",
        json={"token": invite_token},
        headers=csrf_headers(http_client),
    )
    assert second_accept.status_code in (400, 401, 409), (
        f"Expected failure on second accept, got {second_accept.status_code}: {second_accept.text}"
    )


# ── Test 5: invitation email mismatch rejected ────────────────────────────────


def test_invitation_email_mismatch_rejected(http_client: TestClient, fake_email) -> None:
    """A user logged in as email2 cannot accept an invitation sent to email1."""
    _setup_admin(http_client, fake_email, "inv5_admin@example.com", "Inv5 Org")
    headers = csrf_headers(http_client)

    email1 = "inv5_target1@example.com"
    email2 = "inv5_target2@example.com"

    resp = http_client.post(
        "/api/v1/workspace/invitations",
        json={"email": email1, "role": "recruiter"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    invite_token = _extract_invite_token(fake_email, email1)

    # Register and log in as the *wrong* user (email2)
    register_and_verify(http_client, fake_email, email2)
    login(http_client, email2)

    resp = http_client.post(
        "/api/v1/workspace/invitations/accept",
        json={"token": invite_token},
        headers=csrf_headers(http_client),
    )
    assert resp.status_code in (400, 403), (
        f"Expected 400 or 403 for email mismatch, got {resp.status_code}: {resp.text}"
    )
    assert resp.json()["detail"]["error"] == "EMAIL_MISMATCH"


# ── Test 6: accept invitation requires CSRF ───────────────────────────────────


def test_accept_invitation_requires_csrf(http_client: TestClient, fake_email) -> None:
    """POST /invitations/accept without an X-CSRF-Token header must return 403."""
    _setup_admin(http_client, fake_email, "inv6_admin@example.com", "Inv6 Org")
    headers = csrf_headers(http_client)

    invited_email = "inv6_target@example.com"
    resp = http_client.post(
        "/api/v1/workspace/invitations",
        json={"email": invited_email, "role": "recruiter"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    invite_token = _extract_invite_token(fake_email, invited_email)

    register_and_verify(http_client, fake_email, invited_email)
    login(http_client, invited_email)

    # Deliberately omit the CSRF header
    resp = http_client.post(
        "/api/v1/workspace/invitations/accept",
        json={"token": invite_token},
        # No headers= argument → no X-CSRF-Token
    )
    assert resp.status_code == 403, (
        f"Expected 403 without CSRF, got {resp.status_code}: {resp.text}"
    )


# ── Test 7: invited email can register then accept ────────────────────────────


def test_invited_email_can_register_then_accept(
    http_client: TestClient, fake_email, db_session: SASession
) -> None:
    """Full happy-path: invite → register + verify → login → accept → member."""
    _setup_admin(http_client, fake_email, "inv7_admin@example.com", "Inv7 Org")
    headers = csrf_headers(http_client)

    invited_email = "inv7_target@example.com"
    resp = http_client.post(
        "/api/v1/workspace/invitations",
        json={"email": invited_email, "role": "reviewer"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text

    # Capture invite token before registering (avoids email ordering issues)
    invite_token = _extract_invite_token(fake_email, invited_email)

    # Invited user registers and verifies their account
    register_and_verify(http_client, fake_email, invited_email)
    login(http_client, invited_email)

    resp = http_client.post(
        "/api/v1/workspace/invitations/accept",
        json={"token": invite_token},
        headers=csrf_headers(http_client),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["role"] == "reviewer"
    assert "organization" in body

    # Confirm the membership exists in the DB
    user = db_session.query(User).filter(User.email == invited_email).first()
    assert user is not None
    membership = (
        db_session.query(Membership)
        .filter(
            Membership.user_id == user.id,
            Membership.is_active.is_(True),
        )
        .all()
    )
    # The user has their own personal workspace + the org they just joined
    org_ids = {m.org_id for m in membership}
    assert len(org_ids) >= 2, (
        f"Expected at least 2 active memberships (personal + invited org), got: {len(org_ids)}"
    )


# ── Test 8: admin invitation grants admin role ────────────────────────────────


def test_admin_invitation_grants_admin_role(
    http_client: TestClient, fake_email, db_session: SASession
) -> None:
    """Inviting a user with role='admin' produces a membership with role 'admin'."""
    _setup_admin(http_client, fake_email, "inv8_admin@example.com", "Inv8 Org")
    headers = csrf_headers(http_client)

    invited_email = "inv8_target@example.com"
    resp = http_client.post(
        "/api/v1/workspace/invitations",
        json={"email": invited_email, "role": "admin"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text

    invite_token = _extract_invite_token(fake_email, invited_email)

    register_and_verify(http_client, fake_email, invited_email)
    login(http_client, invited_email)

    resp = http_client.post(
        "/api/v1/workspace/invitations/accept",
        json={"token": invite_token},
        headers=csrf_headers(http_client),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["role"] == "admin"

    # Cross-check the membership row in the DB
    user = db_session.query(User).filter(User.email == invited_email).first()
    assert user is not None
    # Find the membership for the org they were invited to (not their personal workspace)
    invitation = (
        db_session.query(OrganizationInvitation)
        .filter(OrganizationInvitation.email == invited_email)
        .first()
    )
    assert invitation is not None
    membership = (
        db_session.query(Membership)
        .filter(
            Membership.user_id == user.id,
            Membership.org_id == invitation.org_id,
        )
        .first()
    )
    assert membership is not None, "Membership row not found after accepting invitation"
    assert membership.role == "admin", (
        f"Expected role 'admin' on membership, got '{membership.role}'"
    )
    assert membership.is_active is True
