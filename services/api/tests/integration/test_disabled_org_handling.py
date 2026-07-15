"""Integration tests for disabled organization state validation.

Invariants verified:
  1. Login with only-disabled-org membership → null org context
  2. preview_invitation for disabled org → 410 ORGANIZATION_INACTIVE
  3. accept_invitation for disabled org → 410 ORGANIZATION_INACTIVE
  4. accept_invitation_new_user for disabled org → 410 ORGANIZATION_INACTIVE
  5. list_user_organizations excludes disabled orgs
"""

import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session as SASession

from app.models.organization import Organization
from app.models.user import User
from tests.integration.conftest import csrf_headers, login, register_and_verify

pytestmark = pytest.mark.integration

_PASSWORD = "TestPassword123!"
_NEW_PASSWORD = "NewInvitee456!xyz"


def _disable_org(db: SASession, org_id: str) -> None:
    db.query(Organization).filter(Organization.id == org_id).update({"is_active": False})
    db.flush()


# ── 1. Login with disabled-org membership → null org_id ─────────────────────


def test_login_with_disabled_org_returns_null_org_id(
    http_client: TestClient, fake_email, db_session: SASession
):
    """Login must not pick a membership in a disabled org as default context."""
    email = "disorg1@example.com"
    register_and_verify(http_client, fake_email, email, password=_PASSWORD)
    login(http_client, email, password=_PASSWORD)

    me = http_client.get("/api/v1/auth/me").json()
    org_id = me["org_id"]
    assert org_id is not None, "Should have active org after registration"

    # Disable the org
    _disable_org(db_session, org_id)

    # Log in again — should see null org
    logout_resp = http_client.post("/api/v1/auth/logout", headers=csrf_headers(http_client))
    assert logout_resp.status_code == 200

    login(http_client, email, password=_PASSWORD)
    me2 = http_client.get("/api/v1/auth/me").json()
    assert me2["org_id"] is None, (
        f"Expected null org_id after login with disabled org, got {me2['org_id']!r}"
    )


# ── 2. preview_invitation for disabled org → 410 ────────────────────────────


def test_preview_invitation_disabled_org_returns_410(
    http_client: TestClient, fake_email, db_session: SASession
):
    """preview_invitation must return 410 when the org is disabled."""
    admin_email = "disorg2_admin@example.com"
    register_and_verify(http_client, fake_email, admin_email, password=_PASSWORD)
    login(http_client, admin_email, password=_PASSWORD)
    headers = csrf_headers(http_client)

    me = http_client.get("/api/v1/auth/me").json()
    org_id = me["org_id"]

    # Send invitation
    resp = http_client.post(
        "/api/v1/workspace/invitations",
        json={"email": "disorg2_target@example.com", "role": "recruiter"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text

    sent = fake_email.invitation_message_for("disorg2_target@example.com")
    assert sent is not None
    m = re.search(r"invite/([0-9a-f]{64})", sent.text_body)
    assert m
    token = m.group(1)

    # Disable the org
    _disable_org(db_session, org_id)

    # Preview should now return 410
    resp = http_client.get(f"/api/v1/workspace/invitations/preview?token={token}")
    assert resp.status_code == 410, (
        f"Expected 410 for disabled org on preview, got {resp.status_code}: {resp.text}"
    )
    error = resp.json().get("detail", {}).get("error")
    assert error == "ORGANIZATION_INACTIVE", f"Expected ORGANIZATION_INACTIVE, got {error!r}"


# ── 3. accept_invitation for disabled org → 410 ──────────────────────────────


def test_accept_invitation_disabled_org_returns_410(
    http_client: TestClient, fake_email, db_session: SASession
):
    """Existing-user accept_invitation must return 410 when the org is disabled."""
    from app.main import app

    admin_email = "disorg3_admin@example.com"
    invitee_email = "disorg3_target@example.com"

    register_and_verify(http_client, fake_email, admin_email, password=_PASSWORD)
    login(http_client, admin_email, password=_PASSWORD)
    headers = csrf_headers(http_client)

    me = http_client.get("/api/v1/auth/me").json()
    org_id = me["org_id"]

    resp = http_client.post(
        "/api/v1/workspace/invitations",
        json={"email": invitee_email, "role": "recruiter"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text

    sent = fake_email.invitation_message_for(invitee_email)
    assert sent is not None
    m = re.search(r"invite/([0-9a-f]{64})", sent.text_body)
    assert m
    token = m.group(1)

    # Register invitee
    register_and_verify(http_client, fake_email, invitee_email, password=_PASSWORD)

    # Disable the org before invitee accepts
    _disable_org(db_session, org_id)

    with TestClient(app, raise_server_exceptions=True) as c:
        c.post("/api/v1/auth/login", json={"email": invitee_email, "password": _PASSWORD})
        csrf = c.cookies.get("es_csrf")
        resp = c.post(
            "/api/v1/workspace/invitations/accept",
            json={"token": token},
            headers={"X-CSRF-Token": csrf},
        )
        assert resp.status_code == 410, (
            f"Expected 410 for disabled org on accept, got {resp.status_code}: {resp.text}"
        )
        error = resp.json().get("detail", {}).get("error")
        assert error == "ORGANIZATION_INACTIVE", f"Expected ORGANIZATION_INACTIVE, got {error!r}"


# ── 4. accept_invitation_new_user for disabled org → 410 ─────────────────────


def test_accept_invitation_new_user_disabled_org_returns_410(
    http_client: TestClient, fake_email, db_session: SASession
):
    """New-user accept_invitation_new_user must return 410 when the org is disabled."""
    from app.main import app

    admin_email = "disorg4_admin@example.com"
    invitee_email = "disorg4_target@example.com"

    register_and_verify(http_client, fake_email, admin_email, password=_PASSWORD)
    login(http_client, admin_email, password=_PASSWORD)
    headers = csrf_headers(http_client)

    me = http_client.get("/api/v1/auth/me").json()
    org_id = me["org_id"]

    resp = http_client.post(
        "/api/v1/workspace/invitations",
        json={"email": invitee_email, "role": "recruiter"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text

    sent = fake_email.invitation_message_for(invitee_email)
    assert sent is not None
    m = re.search(r"invite/([0-9a-f]{64})", sent.text_body)
    assert m
    token = m.group(1)

    # Disable the org before new user accepts
    _disable_org(db_session, org_id)

    with TestClient(app, raise_server_exceptions=True) as c:
        resp = c.post(
            "/api/v1/workspace/invitations/accept-new",
            json={
                "token": token,
                "full_name": "New Invitee",
                "password": _NEW_PASSWORD,
                "terms_accepted": True,
                "privacy_notice_accepted": True,
                "terms_version": "2026-07-01",
                "privacy_notice_version": "2026-07-01",
            },
        )
        assert resp.status_code == 410, (
            f"Expected 410 for disabled org on accept-new, got {resp.status_code}: {resp.text}"
        )
        error = resp.json().get("detail", {}).get("error")
        assert error == "ORGANIZATION_INACTIVE", f"Expected ORGANIZATION_INACTIVE, got {error!r}"


# ── 5. list_user_organizations excludes disabled orgs ────────────────────────


def test_list_organizations_excludes_disabled_orgs(
    http_client: TestClient, fake_email, db_session: SASession
):
    """list_user_organizations must not return disabled organizations."""
    email = "disorg5@example.com"
    register_and_verify(http_client, fake_email, email, password=_PASSWORD)
    login(http_client, email, password=_PASSWORD)

    me = http_client.get("/api/v1/auth/me").json()
    org_id = me["org_id"]
    assert org_id is not None

    # Verify org appears in list
    resp = http_client.get("/api/v1/workspace/organizations")
    assert resp.status_code == 200
    org_ids_before = [o["id"] for o in resp.json()["organizations"]]
    assert org_id in org_ids_before, "Org should appear before being disabled"

    # Disable the org
    _disable_org(db_session, org_id)

    # List must exclude it now
    from app.services.workspace import list_user_organizations

    user = db_session.query(User).filter(User.email == email).first()
    assert user is not None
    orgs = list_user_organizations(db_session, user.id)
    org_ids_after = [o.id for o in orgs]
    assert org_id not in org_ids_after, (
        f"Disabled org {org_id!r} must not appear in list_user_organizations"
    )
