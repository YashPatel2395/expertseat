"""CSRF enforcement inventory tests.

Verifies that every state-changing endpoint rejects requests without an
X-CSRF-Token header (returning 403 CSRF_VALIDATION_FAILED), and that the
explicitly exempt endpoints accept requests without the header.
"""

import re

import pytest

from tests.integration.conftest import csrf_headers, login, register_and_verify

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _unique_email(tag: str) -> str:
    """Return a deterministic but tag-unique test email address."""
    safe = tag.replace("/", "_").replace(" ", "_").lower()
    return f"csrf_{safe}@example.com"


def _setup_user(http_client, fake_email, tag: str):
    """Register, verify, and log in a fresh user. Returns (email, password)."""
    email = _unique_email(tag)
    password = "Password123!"
    register_and_verify(http_client, fake_email, email, password)
    login(http_client, email, password)
    return email, password


def _get_me(http_client) -> dict:
    """Return the /auth/me payload for the currently authenticated user."""
    resp = http_client.get("/api/v1/auth/me")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _create_second_member(http_client, fake_email, org_id: str, inviter_headers: dict) -> str:
    """Invite + register + accept a second member and return their user_id."""
    invitee_email = "csrf_invitee_member@example.com"
    inv_resp = http_client.post(
        "/api/v1/workspace/invitations",
        json={"email": invitee_email, "role": "recruiter"},
        headers=inviter_headers,
    )
    assert inv_resp.status_code == 201, inv_resp.text

    inv_email = fake_email.last_to(invitee_email)
    assert inv_email, "No invitation email sent"
    match = re.search(r"/invite/([0-9a-f]{64})", inv_email.text_body)
    assert match, "No invite token in invitation email"
    invite_token = match.group(1)

    register_and_verify(http_client, fake_email, invitee_email)
    login(http_client, invitee_email)
    http_client.post(
        "/api/v1/workspace/invitations/accept",
        json={"token": invite_token},
        headers=csrf_headers(http_client),
    )

    # Switch back to admin context
    login(http_client, "csrf_admin_forsetup@example.com")
    http_client.post(
        "/api/v1/auth/switch-org",
        json={"org_id": org_id},
        headers=csrf_headers(http_client),
    )

    resp = http_client.get("/api/v1/workspace/members")
    members = resp.json()["members"]
    invitee = next((m for m in members if m["email"] == invitee_email), None)
    assert invitee, "Invitee not found in member list"
    return invitee["user_id"]


# ---------------------------------------------------------------------------
# Individual tests — one per state-changing endpoint
# ---------------------------------------------------------------------------


def test_csrf_required_auth_refresh(http_client, fake_email):
    """POST /api/v1/auth/refresh rejects missing CSRF."""
    _setup_user(http_client, fake_email, "auth_refresh")
    resp = http_client.post("/api/v1/auth/refresh")  # no CSRF header
    assert resp.status_code == 403
    assert resp.json()["detail"]["error"] == "CSRF_VALIDATION_FAILED"


def test_csrf_required_auth_logout(http_client, fake_email):
    """POST /api/v1/auth/logout rejects missing CSRF."""
    _setup_user(http_client, fake_email, "auth_logout")
    resp = http_client.post("/api/v1/auth/logout")  # no CSRF header
    assert resp.status_code == 403
    assert resp.json()["detail"]["error"] == "CSRF_VALIDATION_FAILED"


def test_csrf_required_auth_logout_all(http_client, fake_email):
    """POST /api/v1/auth/logout-all rejects missing CSRF."""
    _setup_user(http_client, fake_email, "auth_logout_all")
    resp = http_client.post("/api/v1/auth/logout-all")  # no CSRF header
    assert resp.status_code == 403
    assert resp.json()["detail"]["error"] == "CSRF_VALIDATION_FAILED"


def test_csrf_required_auth_switch_org(http_client, fake_email):
    """POST /api/v1/auth/switch-org rejects missing CSRF."""
    _setup_user(http_client, fake_email, "auth_switch_org")
    me = _get_me(http_client)
    resp = http_client.post(
        "/api/v1/auth/switch-org",
        json={"org_id": me["org_id"]},
    )  # no CSRF header
    assert resp.status_code == 403
    assert resp.json()["detail"]["error"] == "CSRF_VALIDATION_FAILED"


def test_csrf_required_auth_change_password(http_client, fake_email):
    """POST /api/v1/auth/change-password rejects missing CSRF."""
    _setup_user(http_client, fake_email, "auth_change_password")
    resp = http_client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "Password123!", "new_password": "NewPassword456!"},
    )  # no CSRF header
    assert resp.status_code == 403
    assert resp.json()["detail"]["error"] == "CSRF_VALIDATION_FAILED"


def test_csrf_required_workspace_create_organization(http_client, fake_email):
    """POST /api/v1/workspace/organizations rejects missing CSRF."""
    _setup_user(http_client, fake_email, "ws_create_org")
    resp = http_client.post(
        "/api/v1/workspace/organizations",
        json={"name": "No CSRF Org"},
    )  # no CSRF header
    assert resp.status_code == 403
    assert resp.json()["detail"]["error"] == "CSRF_VALIDATION_FAILED"


def test_csrf_required_workspace_update_settings(http_client, fake_email):
    """PATCH /api/v1/workspace/settings rejects missing CSRF."""
    _setup_user(http_client, fake_email, "ws_update_settings")
    resp = http_client.patch(
        "/api/v1/workspace/settings",
        json={"name": "Renamed Without CSRF"},
    )  # no CSRF header
    assert resp.status_code == 403
    assert resp.json()["detail"]["error"] == "CSRF_VALIDATION_FAILED"


def _setup_admin_with_member(http_client, fake_email, admin_tag: str):
    """
    Create an admin user in a fresh org, add a second member, and return
    (org_id, second_user_id).  The http_client is left authenticated as admin.
    """
    admin_email = f"csrf_{admin_tag}_admin@example.com"
    admin_password = "Password123!"
    register_and_verify(http_client, fake_email, admin_email, admin_password)
    login(http_client, admin_email, admin_password)
    hdrs = csrf_headers(http_client)

    # Create a dedicated org so we're not operating on the default workspace
    org_resp = http_client.post(
        "/api/v1/workspace/organizations",
        json={"name": f"CSRF Test Org {admin_tag}"},
        headers=hdrs,
    )
    assert org_resp.status_code == 201, org_resp.text
    org_id = org_resp.json()["id"]

    # Switch into new org
    http_client.post("/api/v1/auth/switch-org", json={"org_id": org_id}, headers=hdrs)
    hdrs = csrf_headers(http_client)

    # Invite a second member
    invitee_email = f"csrf_{admin_tag}_invitee@example.com"
    inv_resp = http_client.post(
        "/api/v1/workspace/invitations",
        json={"email": invitee_email, "role": "recruiter"},
        headers=hdrs,
    )
    assert inv_resp.status_code == 201, inv_resp.text

    inv_email = fake_email.last_to(invitee_email)
    assert inv_email, "No invitation email sent"
    match = re.search(r"/invite/([0-9a-f]{64})", inv_email.text_body)
    assert match, "No invite token found in invitation email"
    invite_token = match.group(1)

    register_and_verify(http_client, fake_email, invitee_email)
    login(http_client, invitee_email)
    http_client.post(
        "/api/v1/workspace/invitations/accept",
        json={"token": invite_token},
        headers=csrf_headers(http_client),
    )

    # Return to admin session in the dedicated org
    login(http_client, admin_email, admin_password)
    http_client.post(
        "/api/v1/auth/switch-org",
        json={"org_id": org_id},
        headers=csrf_headers(http_client),
    )

    members_resp = http_client.get("/api/v1/workspace/members")
    members = members_resp.json()["members"]
    invitee_member = next((m for m in members if m["email"] == invitee_email), None)
    assert invitee_member, "Invitee not found in member list"

    return org_id, invitee_member["user_id"]


def test_csrf_required_workspace_update_member_role(http_client, fake_email):
    """PATCH /api/v1/workspace/members/{user_id} rejects missing CSRF."""
    _org_id, user_id = _setup_admin_with_member(http_client, fake_email, "patch_role")
    resp = http_client.patch(
        f"/api/v1/workspace/members/{user_id}",
        json={"role": "reviewer"},
    )  # no CSRF header
    assert resp.status_code == 403
    assert resp.json()["detail"]["error"] == "CSRF_VALIDATION_FAILED"


def test_csrf_required_workspace_update_member_status(http_client, fake_email):
    """PATCH /api/v1/workspace/members/{user_id}/status rejects missing CSRF."""
    _org_id, user_id = _setup_admin_with_member(http_client, fake_email, "patch_status")
    resp = http_client.patch(
        f"/api/v1/workspace/members/{user_id}/status",
        json={"is_active": False},
    )  # no CSRF header
    assert resp.status_code == 403
    assert resp.json()["detail"]["error"] == "CSRF_VALIDATION_FAILED"


def test_csrf_required_workspace_delete_member(http_client, fake_email):
    """DELETE /api/v1/workspace/members/{user_id} rejects missing CSRF."""
    _org_id, user_id = _setup_admin_with_member(http_client, fake_email, "delete_member")
    resp = http_client.delete(
        f"/api/v1/workspace/members/{user_id}",
    )  # no CSRF header
    assert resp.status_code == 403
    assert resp.json()["detail"]["error"] == "CSRF_VALIDATION_FAILED"


def _setup_admin_with_pending_invitation(http_client, fake_email, tag: str):
    """
    Set up an admin in a fresh org and create a pending invitation.
    Returns (org_id, invitation_id).  The http_client is left as admin.
    """
    admin_email = f"csrf_{tag}_admin@example.com"
    admin_password = "Password123!"
    register_and_verify(http_client, fake_email, admin_email, admin_password)
    login(http_client, admin_email, admin_password)
    hdrs = csrf_headers(http_client)

    org_resp = http_client.post(
        "/api/v1/workspace/organizations",
        json={"name": f"CSRF Inv Org {tag}"},
        headers=hdrs,
    )
    assert org_resp.status_code == 201, org_resp.text
    org_id = org_resp.json()["id"]

    http_client.post("/api/v1/auth/switch-org", json={"org_id": org_id}, headers=hdrs)
    hdrs = csrf_headers(http_client)

    inv_resp = http_client.post(
        "/api/v1/workspace/invitations",
        json={"email": f"csrf_{tag}_pending@example.com", "role": "recruiter"},
        headers=hdrs,
    )
    assert inv_resp.status_code == 201, inv_resp.text
    invitation_id = inv_resp.json()["id"]

    return org_id, invitation_id


def test_csrf_required_workspace_create_invitation(http_client, fake_email):
    """POST /api/v1/workspace/invitations rejects missing CSRF."""
    _setup_user(http_client, fake_email, "ws_create_inv")
    resp = http_client.post(
        "/api/v1/workspace/invitations",
        json={"email": "target@example.com", "role": "recruiter"},
    )  # no CSRF header
    assert resp.status_code == 403
    assert resp.json()["detail"]["error"] == "CSRF_VALIDATION_FAILED"


def test_csrf_required_workspace_delete_invitation(http_client, fake_email):
    """DELETE /api/v1/workspace/invitations/{invitation_id} rejects missing CSRF."""
    _org_id, invitation_id = _setup_admin_with_pending_invitation(
        http_client, fake_email, "delete_inv"
    )
    resp = http_client.delete(
        f"/api/v1/workspace/invitations/{invitation_id}",
    )  # no CSRF header
    assert resp.status_code == 403
    assert resp.json()["detail"]["error"] == "CSRF_VALIDATION_FAILED"


def test_csrf_required_workspace_accept_invitation(http_client, fake_email):
    """POST /api/v1/workspace/invitations/accept rejects missing CSRF."""
    _setup_user(http_client, fake_email, "ws_accept_inv")
    # Use a syntactically valid but non-existent token — CSRF is checked first
    fake_token = "a" * 64
    resp = http_client.post(
        "/api/v1/workspace/invitations/accept",
        json={"token": fake_token},
    )  # no CSRF header
    assert resp.status_code == 403
    assert resp.json()["detail"]["error"] == "CSRF_VALIDATION_FAILED"


# ---------------------------------------------------------------------------
# Exempt endpoints smoke test
# ---------------------------------------------------------------------------


def test_exempt_endpoints_do_not_require_csrf(http_client, fake_email):
    """Verify that exempt (unauthenticated) endpoints accept requests without CSRF.

    This confirms the CSRF middleware is not applied globally — only to
    state-changing authenticated routes.
    """
    # POST /api/v1/auth/register — no CSRF, no auth
    resp = http_client.post(
        "/api/v1/auth/register",
        json={
            "email": "exempt_test_register@example.com",
            "password": "Password123!",
            "full_name": "Exempt Tester",
        },
    )
    assert resp.status_code == 201, resp.text

    # POST /api/v1/auth/login — no CSRF, no auth
    resp = http_client.post(
        "/api/v1/auth/login",
        json={"email": "exempt_test_register@example.com", "password": "Password123!"},
    )
    # 401 because email is not verified — but NOT 403, proving CSRF is not checked
    assert resp.status_code != 403

    # POST /api/v1/auth/forgot-password — no CSRF, no auth
    resp = http_client.post(
        "/api/v1/auth/forgot-password",
        json={"email": "nobody@example.com"},
    )
    assert resp.status_code == 200, resp.text

    # POST /api/v1/auth/resend-verification — no CSRF, no auth
    resp = http_client.post(
        "/api/v1/auth/resend-verification",
        json={"email": "nobody@example.com"},
    )
    assert resp.status_code == 200, resp.text

    # POST /api/v1/auth/reset-password — no CSRF, no auth (will 422 on bad token format, not 403)
    resp = http_client.post(
        "/api/v1/auth/reset-password",
        json={"token": "b" * 64, "new_password": "Password123!"},
    )
    assert resp.status_code != 403
