"""Integration tests for invitation delivery status tracking.

With the transactional outbox the HTTP response always returns
delivery_status='queued' regardless of SMTP outcome (enumeration resistance).
The outbox row tracks the actual delivery state.

Covers:
  1. HTTP response always returns delivery_status='queued'
  2. Outbox row is marked 'sent' after successful in-process delivery
  3. Outbox row stays 'pending' after SMTP failure (row not 'failed')
  4. Invitation resend rotates the token and creates a new outbox row
  5. Failed delivery (outbox retry) does not block a subsequent resend
  6. Raw invitation tokens are never exposed in the API response
"""

import re
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session as SASession

from app.models.organization import OrganizationInvitation
from app.models.outbox import EmailOutbox
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


# ── 1. HTTP response is always 'queued' (enumeration resistance) ──────────────


def test_invitation_delivery_status_is_queued(
    http_client: TestClient, fake_email, db_session: SASession
):
    """Invitation creation must return delivery_status='queued' regardless of SMTP outcome."""
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
    assert body["delivery_status"] == "queued", (
        f"Expected delivery_status='queued' (outbox pattern), got {body['delivery_status']!r}"
    )

    db_session.expire_all()
    inv = (
        db_session.query(OrganizationInvitation)
        .filter(OrganizationInvitation.email == invited_email)
        .first()
    )
    assert inv is not None, "Invitation record not found in DB"
    assert inv.delivery_status == "queued", (
        f"Expected inv.delivery_status='queued', got {inv.delivery_status!r}"
    )
    assert inv.delivery_attempted_at is not None, (
        "delivery_attempted_at must be set (outbox enqueue counts as an attempt)"
    )


# ── 2. Outbox row is 'sent' after successful in-process delivery ──────────────


def test_outbox_row_sent_after_successful_delivery(
    http_client: TestClient, fake_email, db_session: SASession
):
    """When the provider succeeds, the outbox row must be marked 'sent'."""
    headers = _setup_admin_with_org(
        http_client, fake_email, "deliv2_admin@example.com", "Delivery Org 2"
    )
    invited_email = "deliv2_target@example.com"

    _inv_q = db_session.query(EmailOutbox).filter(EmailOutbox.message_type == "invitation")
    before_count = _inv_q.count()

    resp = http_client.post(
        "/api/v1/workspace/invitations",
        json={"email": invited_email, "role": "recruiter"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text

    db_session.expire_all()
    after_count = (
        db_session.query(EmailOutbox).filter(EmailOutbox.message_type == "invitation").count()
    )
    assert after_count == before_count + 1, "Expected one new outbox row"

    outbox_row = (
        db_session.query(EmailOutbox)
        .filter(EmailOutbox.message_type == "invitation", EmailOutbox.status == "sent")
        .order_by(EmailOutbox.created_at.desc())
        .first()
    )
    assert outbox_row is not None, "Outbox row must be 'sent' after successful delivery"
    assert outbox_row.sent_at is not None, "sent_at must be set when delivery succeeds"


# ── 3. Outbox row stays 'pending' after SMTP failure ─────────────────────────


def test_outbox_row_pending_after_smtp_failure(
    http_client: TestClient, fake_email, db_session: SASession
):
    """When SMTP fails, the HTTP response is still 201 'queued' and the outbox row is pending."""
    headers = _setup_admin_with_org(
        http_client, fake_email, "deliv3_admin@example.com", "Delivery Org 3"
    )
    invited_email = "deliv3_target@example.com"

    with patch.object(fake_email, "send", side_effect=Exception("SMTP down")):
        resp = http_client.post(
            "/api/v1/workspace/invitations",
            json={"email": invited_email, "role": "recruiter"},
            headers=headers,
        )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["delivery_status"] == "queued", (
        f"HTTP response must be 'queued' even on SMTP failure; got {body['delivery_status']!r}"
    )

    db_session.expire_all()
    outbox_row = (
        db_session.query(EmailOutbox)
        .filter(
            EmailOutbox.message_type == "invitation",
            EmailOutbox.status.in_(["pending", "retry"]),
        )
        .order_by(EmailOutbox.created_at.desc())
        .first()
    )
    assert outbox_row is not None, "Outbox row must be retryable after SMTP failure"
    assert outbox_row.attempt_count >= 1, "attempt_count must be incremented on failure"
    assert outbox_row.failure_code is not None, "failure_code must be set on SMTP failure"


# ── 4. Invitation resend rotates the token ────────────────────────────────────


def test_invitation_resend_rotates_token(
    http_client: TestClient, fake_email, db_session: SASession
):
    _setup_admin_with_org(http_client, fake_email, "deliv4_admin@example.com", "Delivery Org 4")
    invited_email = "deliv4_target@example.com"

    resp = http_client.post(
        "/api/v1/workspace/invitations",
        json={"email": invited_email, "role": "recruiter"},
        headers=csrf_headers(http_client),
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
        headers=csrf_headers(http_client),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["delivery_status"] == "queued", (
        f"Resend must return 'queued'; got {resp.json()['delivery_status']!r}"
    )

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


# ── 5. Failed delivery (outbox retry) does not block resend ──────────────────


def test_failed_delivery_does_not_block_resend(
    http_client: TestClient, fake_email, db_session: SASession
):
    """A pending/failed outbox row must not prevent a successful resend."""
    _setup_admin_with_org(http_client, fake_email, "deliv5_admin@example.com", "Delivery Org 5")
    invited_email = "deliv5_target@example.com"

    # Create invitation with simulated SMTP failure
    with patch.object(fake_email, "send", side_effect=Exception("SMTP down")):
        resp = http_client.post(
            "/api/v1/workspace/invitations",
            json={"email": invited_email, "role": "recruiter"},
            headers=csrf_headers(http_client),
        )
    assert resp.status_code == 201, resp.text
    assert resp.json()["delivery_status"] == "queued"
    invitation_id = resp.json()["id"]

    # Resend without the patch — delivery should now succeed
    resp = http_client.post(
        f"/api/v1/workspace/invitations/{invitation_id}/resend",
        headers=csrf_headers(http_client),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["delivery_status"] == "queued", (
        "Resend response must be 'queued' regardless of SMTP outcome"
    )

    # Verify the latest outbox row is 'sent' (FakeEmailProvider succeeded)
    db_session.expire_all()
    latest_sent = (
        db_session.query(EmailOutbox)
        .filter(EmailOutbox.message_type == "invitation", EmailOutbox.status == "sent")
        .order_by(EmailOutbox.created_at.desc())
        .first()
    )
    assert latest_sent is not None, "Resend outbox row must be 'sent' when provider succeeds"


# ── 6. Raw token not exposed in invitation response ───────────────────────────


def test_raw_token_not_in_invitation_response(
    http_client: TestClient, fake_email, db_session: SASession
):
    _setup_admin_with_org(http_client, fake_email, "deliv6_admin@example.com", "Delivery Org 6")
    invited_email = "deliv6_target@example.com"

    resp = http_client.post(
        "/api/v1/workspace/invitations",
        json={"email": invited_email, "role": "recruiter"},
        headers=csrf_headers(http_client),
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
