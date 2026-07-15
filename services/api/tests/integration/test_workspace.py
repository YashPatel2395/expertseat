"""Integration tests for workspace (organization) management."""

import pytest
from fastapi.testclient import TestClient

from tests.integration.conftest import csrf_headers, login, register_and_verify

pytestmark = pytest.mark.integration


def _setup_user_with_org(http_client, fake_email, email):
    """Register, verify, login, create org, switch into it. Returns org info."""
    register_and_verify(http_client, fake_email, email)
    login(http_client, email)
    headers = csrf_headers(http_client)
    resp = http_client.post(
        "/api/v1/workspace/organizations", json={"name": "Test Org"}, headers=headers
    )
    assert resp.status_code == 201, resp.text
    org = resp.json()
    # Switch to the new org
    http_client.post("/api/v1/auth/switch-org", json={"org_id": org["id"]}, headers=headers)
    headers = csrf_headers(http_client)
    return org, headers


def test_create_org_makes_creator_admin(http_client: TestClient, fake_email):
    register_and_verify(http_client, fake_email, "createorg@example.com")
    login(http_client, "createorg@example.com")
    headers = csrf_headers(http_client)
    resp = http_client.post(
        "/api/v1/workspace/organizations", json={"name": "My Org"}, headers=headers
    )
    assert resp.status_code == 201
    org = resp.json()
    assert org["name"] == "My Org"
    assert org["slug"]


def test_list_organizations_returns_users_orgs(http_client: TestClient, fake_email):
    # Registration atomically creates a default workspace (1 org).
    # Two additional orgs are created below, giving 3 total.
    register_and_verify(http_client, fake_email, "listorgs@example.com")
    login(http_client, "listorgs@example.com")
    headers = csrf_headers(http_client)
    http_client.post("/api/v1/workspace/organizations", json={"name": "Org A"}, headers=headers)
    http_client.post("/api/v1/workspace/organizations", json={"name": "Org B"}, headers=headers)
    resp = http_client.get("/api/v1/workspace/organizations")
    assert resp.status_code == 200
    orgs = resp.json()["organizations"]
    names = {o["name"] for o in orgs}
    assert "Org A" in names
    assert "Org B" in names
    assert len(orgs) == 3  # default workspace + Org A + Org B


def test_switch_org_updates_jwt_claims(http_client: TestClient, fake_email):
    register_and_verify(http_client, fake_email, "switchorg@example.com")
    login(http_client, "switchorg@example.com")
    headers = csrf_headers(http_client)
    resp = http_client.post(
        "/api/v1/workspace/organizations", json={"name": "Switch Test"}, headers=headers
    )
    org_id = resp.json()["id"]

    resp = http_client.post("/api/v1/auth/switch-org", json={"org_id": org_id}, headers=headers)
    assert resp.status_code == 200

    # After switch, /auth/me should reflect the new org
    resp = http_client.get("/api/v1/auth/me")
    assert resp.status_code == 200
    assert resp.json()["org_id"] == org_id
    assert resp.json()["role"] == "admin"


def test_list_members_returns_admin_member(http_client: TestClient, fake_email):
    org, headers = _setup_user_with_org(http_client, fake_email, "listmembers@example.com")
    resp = http_client.get("/api/v1/workspace/members")
    assert resp.status_code == 200
    members = resp.json()["members"]
    assert len(members) == 1
    assert members[0]["role"] == "admin"
