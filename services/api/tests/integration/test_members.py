"""Integration tests for member management and RBAC."""

import pytest
from fastapi.testclient import TestClient

from tests.integration.conftest import csrf_headers, login, register_and_verify

pytestmark = pytest.mark.integration


def _setup_org_with_two_members(
    http_client, fake_email, admin_email, member_email, member_role="recruiter"
):
    """Set up an org with an admin and one other member."""
    register_and_verify(http_client, fake_email, admin_email)
    login(http_client, admin_email)
    headers = csrf_headers(http_client)

    resp = http_client.post(
        "/api/v1/workspace/organizations", json={"name": "RBAC Org"}, headers=headers
    )
    org = resp.json()

    # Switch to org
    http_client.post("/api/v1/auth/switch-org", json={"org_id": org["id"]}, headers=headers)
    headers = csrf_headers(http_client)

    # Invite member
    inv_resp = http_client.post(
        "/api/v1/workspace/invitations",
        json={
            "email": member_email,
            "role": member_role,
        },
        headers=headers,
    )
    assert inv_resp.status_code == 201, inv_resp.text

    # Capture invitation email BEFORE registering (registration overwrites last_to())
    import re

    inv_email = fake_email.last_to(member_email)
    assert inv_email, f"No invitation email sent to {member_email}"
    inv_match = re.search(r"/invite/([0-9a-f]{64})", inv_email.text_body)
    assert inv_match, f"No invite token in invitation email: {inv_email.text_body}"
    invite_token = inv_match.group(1)

    # Register and log in the invited member
    register_and_verify(http_client, fake_email, member_email)
    login(http_client, member_email)

    resp = http_client.post("/api/v1/workspace/invitations/accept", json={"token": invite_token})
    assert resp.status_code == 200, resp.text

    return org


def test_non_admin_cannot_update_role(http_client: TestClient, fake_email):
    org = _setup_org_with_two_members(
        http_client,
        fake_email,
        "admin_roles@example.com",
        "recruiter_roles@example.com",
        "recruiter",
    )
    # Now logged in as recruiter
    http_client.post(
        "/api/v1/auth/switch-org", json={"org_id": org["id"]}, headers=csrf_headers(http_client)
    )
    headers = csrf_headers(http_client)

    # Try to update someone's role as a recruiter
    resp = http_client.get("/api/v1/workspace/members")
    members = resp.json()["members"]
    admin_user_id = next(m["user_id"] for m in members if m["role"] == "admin")

    resp = http_client.patch(
        f"/api/v1/workspace/members/{admin_user_id}", json={"role": "reviewer"}, headers=headers
    )
    assert resp.status_code == 403


def test_last_admin_protection_on_role_change(http_client: TestClient, fake_email):
    register_and_verify(http_client, fake_email, "lastadmin_role@example.com")
    login(http_client, "lastadmin_role@example.com")
    headers = csrf_headers(http_client)

    resp = http_client.post(
        "/api/v1/workspace/organizations", json={"name": "Solo Org"}, headers=headers
    )
    org = resp.json()
    http_client.post("/api/v1/auth/switch-org", json={"org_id": org["id"]}, headers=headers)
    headers = csrf_headers(http_client)

    resp = http_client.get("/api/v1/auth/me")
    user_id = resp.json()["user_id"]

    resp = http_client.patch(
        f"/api/v1/workspace/members/{user_id}", json={"role": "recruiter"}, headers=headers
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["error"] == "LAST_ADMIN_PROTECTED"


def test_last_admin_protection_on_disable(http_client: TestClient, fake_email):
    register_and_verify(http_client, fake_email, "lastadmin_disable@example.com")
    login(http_client, "lastadmin_disable@example.com")
    headers = csrf_headers(http_client)

    resp = http_client.post(
        "/api/v1/workspace/organizations", json={"name": "Disable Org"}, headers=headers
    )
    org = resp.json()
    http_client.post("/api/v1/auth/switch-org", json={"org_id": org["id"]}, headers=headers)
    headers = csrf_headers(http_client)

    resp = http_client.get("/api/v1/auth/me")
    user_id = resp.json()["user_id"]

    resp = http_client.patch(
        f"/api/v1/workspace/members/{user_id}/status", json={"is_active": False}, headers=headers
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["error"] == "LAST_ADMIN_PROTECTED"
