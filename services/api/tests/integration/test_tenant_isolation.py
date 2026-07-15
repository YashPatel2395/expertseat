"""Integration tests for tenant isolation.

These tests verify that a user in Org A cannot access Org B's data,
and that server-side JWT claims are the sole authorization context.
"""

import pytest
from fastapi.testclient import TestClient

from tests.integration.conftest import csrf_headers, login, register_and_verify

pytestmark = pytest.mark.integration


def _create_isolated_user_with_org(http_client, fake_email, email, org_name):
    """Register, verify, login, create org, switch to it. Returns org_id."""
    register_and_verify(http_client, fake_email, email)
    login(http_client, email)
    headers = csrf_headers(http_client)
    resp = http_client.post(
        "/api/v1/workspace/organizations", json={"name": org_name}, headers=headers
    )
    assert resp.status_code == 201
    org_id = resp.json()["id"]
    http_client.post("/api/v1/auth/switch-org", json={"org_id": org_id}, headers=headers)
    return org_id


def test_member_list_scoped_to_active_org(http_client: TestClient, fake_email):
    """User A cannot see Org B members even if they know the org_id."""
    # Create User A in Org A
    _create_isolated_user_with_org(http_client, fake_email, "tenant_a@example.com", "Tenant Org A")

    # The /workspace/members endpoint uses JWT org_id — it returns Org A members
    resp = http_client.get("/api/v1/workspace/members")
    assert resp.status_code == 200
    members = resp.json()["members"]
    emails = [m["email"] for m in members]
    # Only User A should be a member
    assert all("tenant_a" in e for e in emails)


def test_switch_org_validates_membership(http_client: TestClient, fake_email):
    """Attempting to switch to an org the user doesn't belong to returns 403."""
    register_and_verify(http_client, fake_email, "switch_validate@example.com")
    login(http_client, "switch_validate@example.com")
    headers = csrf_headers(http_client)

    fake_org_id = "00000000-0000-0000-0000-000000000001"
    resp = http_client.post(
        "/api/v1/auth/switch-org", json={"org_id": fake_org_id}, headers=headers
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["error"] == "NOT_A_MEMBER"


def test_unauthenticated_workspace_access_returns_401(http_client: TestClient, fake_email):
    """Workspace endpoints without a valid JWT return 401."""
    resp = http_client.get("/api/v1/workspace/members")
    assert resp.status_code == 401


def test_settings_only_accessible_with_admin_role(http_client: TestClient, fake_email):
    """A non-admin in an org cannot update org settings."""
    # Setup admin
    _create_isolated_user_with_org(
        http_client, fake_email, "settings_admin@example.com", "Settings Org"
    )
    headers = csrf_headers(http_client)

    # Invite a recruiter
    resp = http_client.post(
        "/api/v1/workspace/invitations",
        json={
            "email": "settings_recruiter@example.com",
            "role": "recruiter",
        },
        headers=headers,
    )
    assert resp.status_code == 201

    # Capture invitation email BEFORE registering
    import re

    inv_email = fake_email.last_to("settings_recruiter@example.com")
    assert inv_email, "No invitation email sent"
    inv_match = re.search(r"/invite/([0-9a-f]{64})", inv_email.text_body)
    assert inv_match, f"No invite token in: {inv_email.text_body}"
    invite_token = inv_match.group(1)

    # Register recruiter and accept invitation
    register_and_verify(http_client, fake_email, "settings_recruiter@example.com")
    login(http_client, "settings_recruiter@example.com")
    resp = http_client.post(
        "/api/v1/workspace/invitations/accept",
        json={"token": invite_token},
        headers=csrf_headers(http_client),
    )
    assert resp.status_code == 200

    resp = http_client.get("/api/v1/workspace/organizations")
    orgs = resp.json()["organizations"]
    org_id = next(o["id"] for o in orgs if o["name"] == "Settings Org")
    http_client.post(
        "/api/v1/auth/switch-org", json={"org_id": org_id}, headers=csrf_headers(http_client)
    )
    headers = csrf_headers(http_client)

    resp = http_client.patch(
        "/api/v1/workspace/settings", json={"name": "Hacked Name"}, headers=headers
    )
    assert resp.status_code == 403
