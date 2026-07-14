"""Integration tests for invitation delivery status tracking.

Covers:
  1. Successful delivery is recorded with status "sent"
  2. Failed delivery is recorded with status "failed" and a failure code
  3. Resending an invitation rotates the token
  4. A previously-failed delivery does not block a resend
  5. Raw invitation tokens are never exposed in the API response
"""

import re
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session as SASession

from app.models.organization import OrganizationInvitation
from tests.integration.conftest import csrf_headers, login, register_and_verify

pytestmark = pytest.mark.integration

_PASSWORD = "TestPassword123!"


def _setup_admin_with_org(http_client, fake_email, email, org_name):
    """Register + verify + login + create org + switch context. Returns csrf headers."""
    register_and_verify(http_client, fake_email, email, password=_PASSWORD)
    login(http_client, email, password=_PASSWORD)
    headers = csrf_headers(http_client)

    resp = http_client.post(
        "/api/v1/workspace/organizations",
        json={"name": org_name},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    org = resp.json()

    resp = http_client.post(
        "/api/v1/auth/switch-org",
        json={"org_id": org["id"]},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return csrf_headers(http_client)


# ── 1. Successful invitation delivery is recorded ────────────────────────────


def test_successful_invitation_delivery_recorded(
    http_client: TestClient, fake_email, db_session: SASession
):
    headers = _setup_admin_with_org(
        http_client, fake_email, "deliv1_admin@example.com", "Delivery Org 1"
    )
    invited_email = "deliv1_target@example.com"

    resp = http_client.post(
        "/api/v1/workspace/invitations",
        json={"email": invited_email, "role": "recruiter"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["delivery_status"] == "sent", (
        f"Expected delivery_status='sent', got {body['delivery_status']!r}"
    )

    db_session.expire_all()
    inv = (
        db_session.query(OrganizationInvitation)
        .filter(OrganizationInvitation.email == invited_email)
        .first()
    )
    assert inv is not None, "Invitation record not found in DB"
    assert inv.delivery_status == "sent", (
        f"Expected inv.delivery_status='sent', got {inv.delivery_status!r}"
    )
    assert inv.delivery_attempted_at is not None, (
        "delivery_attempted_at must be set after a delivery attempt"
    )


# ── 2. Failed invitation delivery is recorded ────────────────────────────────


def test_failed_invitation_delivery_recorded(
    http_client: TestClient, fake_email, db_session: SASession
):
    headers = _setup_admin_with_org(
        http_client, fake_email, "deliv2_admin@example.com", "Delivery Org 2"
    )
    invited_email = "deliv2_target@example.com"

    with patch.object(fake_email, "send", side_effect=Exception("SMTP down")):
        resp = http_client.post(
            "/api/v1/workspace/invitations",
            json={"email": invited_email, "role": "recruiter"},
            headers=headers,
        )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["delivery_status"] == "failed", (
        f"Expected delivery_status='failed', got {body['delivery_status']!r}"
    )

    db_session.expire_all()
    inv = (
        db_session.query(OrganizationInvitation)
        .filter(OrganizationInvitation.email == invited_email)
        .first()
    )
    assert inv is not None, "Invitation record not found in DB"
    assert inv.delivery_status == "failed", (
        f"Expected inv.delivery_status='failed', got {inv.delivery_status!r}"
    )
    assert inv.delivery_failure_code == "SMTP_ERROR", (
        f"Expected failure_code='SMTP_ERROR', got {inv.delivery_failure_code!r}"
    )


# ── 3. Invitation resend rotates the token ────────────────────────────────────


def test_invitation_resend_rotates_token(
    http_client: TestClient, fake_email, db_session: SASession
):
    headers = _setup_admin_with_org(
        http_client, fake_email, "deliv3_admin@example.com", "Delivery Org 3"
    )
    invited_email = "deliv3_target@example.com"

    resp = http_client.post(
        "/api/v1/workspace/invitations",
        json={"email": invited_email, "role": "recruiter"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    invitation_id = resp.json()["id"]

    db_session.expire_all()
    inv_before = (
        db_session.query(OrganizationInvitation)
        .filter(OrganizationInvitation.id == invitation_id)
        .first()
    )
    assert inv_before is not None
    old_token_hash = inv_before.token_hash

    resp = http_client.post(
        f"/api/v1/workspace/invitations/{invitation_id}/resend",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text

    db_session.expire_all()
    inv_after = (
        db_session.query(OrganizationInvitation)
        .filter(OrganizationInvitation.id == invitation_id)
        .first()
    )
    assert inv_after is not None
    assert inv_after.token_hash != old_token_hash, (
        "Resend must rotate the invitation token (token_hash must change)"
    )
    assert inv_after.delivery_status in ("sent", "pending"), (
        f"Unexpected delivery_status after resend: {inv_after.delivery_status!r}"
    )


# ── 4. Failed delivery does not block resend ─────────────────────────────────


def test_failed_delivery_does_not_block_resend(
    http_client: TestClient, fake_email, db_session: SASession
):
    headers = _setup_admin_with_org(
        http_client, fake_email, "deliv4_admin@example.com", "Delivery Org 4"
    )
    invited_email = "deliv4_target@example.com"

    # Create invitation with a simulated delivery failure
    with patch.object(fake_email, "send", side_effect=Exception("SMTP down")):
        resp = http_client.post(
            "/api/v1/workspace/invitations",
            json={"email": invited_email, "role": "recruiter"},
            headers=headers,
        )
    assert resp.status_code == 201, resp.text
    assert resp.json()["delivery_status"] == "failed"
    invitation_id = resp.json()["id"]

    # Resend without the patch — delivery should now succeed
    resp = http_client.post(
        f"/api/v1/workspace/invitations/{invitation_id}/resend",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["delivery_status"] == "sent", (
        f"Expected delivery_status='sent' after resend, got {resp.json()['delivery_status']!r}"
    )


# ── 5. Raw token not exposed in invitation response ───────────────────────────


def test_raw_token_not_in_invitation_response(
    http_client: TestClient, fake_email, db_session: SASession
):
    headers = _setup_admin_with_org(
        http_client, fake_email, "deliv5_admin@example.com", "Delivery Org 5"
    )
    invited_email = "deliv5_target@example.com"

    resp = http_client.post(
        "/api/v1/workspace/invitations",
        json={"email": invited_email, "role": "recruiter"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()

    # Response must not include raw token fields
    assert "token" not in body, "Raw token must not be returned in invitation response"
    assert "token_hash" not in body, "Token hash must not be returned in invitation response"

    # Response must not contain any 64-char hex string (the raw token)
    response_text = str(body)
    hex64_pattern = re.compile(r"[0-9a-f]{64}")
    matches = hex64_pattern.findall(response_text)
    assert not matches, f"Found potential raw token(s) in invitation response: {matches}"
