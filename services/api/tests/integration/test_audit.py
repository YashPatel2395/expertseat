"""Integration tests for audit log."""

import pytest
from fastapi.testclient import TestClient

from tests.integration.conftest import csrf_headers, login, register_and_verify

pytestmark = pytest.mark.integration


def _admin_with_org(http_client, fake_email, email):
    register_and_verify(http_client, fake_email, email)
    login(http_client, email)
    headers = csrf_headers(http_client)
    resp = http_client.post(
        "/api/v1/workspace/organizations", json={"name": "Audit Org"}, headers=headers
    )
    org_id = resp.json()["id"]
    http_client.post("/api/v1/auth/switch-org", json={"org_id": org_id}, headers=headers)
    return csrf_headers(http_client)


def test_admin_can_read_audit_log(http_client: TestClient, fake_email):
    _admin_with_org(http_client, fake_email, "audit_admin@example.com")
    resp = http_client.get("/api/v1/workspace/audit")
    assert resp.status_code == 200
    events = resp.json()["events"]
    assert any(e["event_type"] == "org.created" for e in events)


def test_non_admin_cannot_read_audit_log(http_client: TestClient, fake_email):
    # Setup admin and org
    headers = _admin_with_org(http_client, fake_email, "audit_admin2@example.com")
    # Invite recruiter
    resp = http_client.post(
        "/api/v1/workspace/invitations",
        json={
            "email": "audit_recruiter@example.com",
            "role": "recruiter",
        },
        headers=headers,
    )
    assert resp.status_code == 201

    # Capture invitation email BEFORE registering
    import re

    inv_email = fake_email.last_to("audit_recruiter@example.com")
    assert inv_email, "No invitation email sent"
    inv_match = re.search(r"/invite/([0-9a-f]{64})", inv_email.text_body)
    assert inv_match, f"No invite token in: {inv_email.text_body}"
    invite_token = inv_match.group(1)

    # Register recruiter and accept invitation
    register_and_verify(http_client, fake_email, "audit_recruiter@example.com")
    login(http_client, "audit_recruiter@example.com")
    resp = http_client.post(
        "/api/v1/workspace/invitations/accept",
        json={"token": invite_token},
        headers=csrf_headers(http_client),
    )
    assert resp.status_code == 200

    resp = http_client.get("/api/v1/workspace/organizations")
    orgs = resp.json()["organizations"]
    org_id = next(o["id"] for o in orgs if o["name"] == "Audit Org")
    http_client.post(
        "/api/v1/auth/switch-org", json={"org_id": org_id}, headers=csrf_headers(http_client)
    )

    resp = http_client.get("/api/v1/workspace/audit")
    assert resp.status_code == 403


def test_org_creation_writes_audit_event(http_client: TestClient, fake_email):
    _admin_with_org(http_client, fake_email, "audit_create@example.com")
    resp = http_client.get("/api/v1/workspace/audit")
    events = resp.json()["events"]
    event_types = [e["event_type"] for e in events]
    assert "org.created" in event_types
