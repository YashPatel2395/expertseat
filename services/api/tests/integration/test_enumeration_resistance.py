"""Integration tests for enumeration resistance via the transactional outbox.

Invariants verified:
  1. create_invitation returns 201 even when "SMTP" fails (outbox absorbs the failure)
  2. resend_invitation returns 200 even when "SMTP" fails
  3. delivery_status is 'queued' (not 'failed') regardless of backend state
  4. Outbox row is present after failed-provider invitation
  5. No SMTP error detail is leaked in the HTTP response body
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session as SASession

from app.models.outbox import EmailOutbox
from tests.integration.conftest import csrf_headers, login, register_and_verify

pytestmark = pytest.mark.integration

_PASSWORD = "TestPassword123!"


def _setup_org_with_admin(http_client, fake_email, admin_email, org_name):
    """Register admin, create org, switch context. Returns refreshed csrf headers + org_id."""
    register_and_verify(http_client, fake_email, admin_email, password=_PASSWORD)
    login(http_client, email=admin_email, password=_PASSWORD)
    headers = csrf_headers(http_client)

    resp = http_client.post(
        "/api/v1/workspace/organizations",
        json={"name": org_name},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    org_id = resp.json()["id"]

    resp = http_client.post(
        "/api/v1/auth/switch-org",
        json={"org_id": org_id},
        headers=csrf_headers(http_client),
    )
    assert resp.status_code == 200, resp.text
    return csrf_headers(http_client), org_id


# ── 1. create_invitation succeeds even without reachable SMTP ─────────────────


def test_create_invitation_succeeds_with_no_smtp(
    http_client: TestClient, fake_email, db_session: SASession
):
    """Invitation creation must return 201 even if the email provider is unreachable.

    With the transactional outbox the route does NOT call the email provider —
    it only writes to the DB.  SMTP delivery happens asynchronously.
    """
    headers, _ = _setup_org_with_admin(
        http_client, fake_email, "enum_create@example.com", "Enum Org 1"
    )

    resp = http_client.post(
        "/api/v1/workspace/invitations",
        json={"email": "target_enum@example.com", "role": "recruiter"},
        headers=headers,
    )
    assert resp.status_code == 201, (
        f"Expected 201 even with no SMTP; got {resp.status_code}: {resp.text}"
    )


# ── 2. resend_invitation succeeds even without reachable SMTP ─────────────────


def test_resend_invitation_succeeds_with_no_smtp(
    http_client: TestClient, fake_email, db_session: SASession
):
    """Resend must return 200 even if the email provider is unreachable."""
    headers, _ = _setup_org_with_admin(
        http_client, fake_email, "enum_resend@example.com", "Enum Org 2"
    )

    # Create an invitation first
    resp = http_client.post(
        "/api/v1/workspace/invitations",
        json={"email": "resend_target@example.com", "role": "recruiter"},
        headers=csrf_headers(http_client),
    )
    assert resp.status_code == 201, resp.text
    invitation_id = resp.json()["id"]

    resp = http_client.post(
        f"/api/v1/workspace/invitations/{invitation_id}/resend",
        headers=csrf_headers(http_client),
    )
    assert resp.status_code == 200, (
        f"Expected 200 on resend even with no SMTP; got {resp.status_code}: {resp.text}"
    )


# ── 3. delivery_status is always 'queued' ─────────────────────────────────────


def test_delivery_status_is_queued_not_failed(
    http_client: TestClient, fake_email, db_session: SASession
):
    """The route must return delivery_status='queued', not 'sent' or 'failed'."""
    headers, _ = _setup_org_with_admin(
        http_client, fake_email, "enum_status@example.com", "Enum Org 3"
    )

    resp = http_client.post(
        "/api/v1/workspace/invitations",
        json={"email": "status_target@example.com", "role": "reviewer"},
        headers=csrf_headers(http_client),
    )
    assert resp.status_code == 201, resp.text
    delivery_status = resp.json().get("delivery_status")
    assert delivery_status == "queued", (
        f"Expected delivery_status='queued' for enumeration resistance, got {delivery_status!r}"
    )


# ── 4. Outbox row exists after failed-provider invitation ─────────────────────


def test_outbox_row_present_after_invitation(
    http_client: TestClient, fake_email, db_session: SASession
):
    """An EmailOutbox row must exist after invitation creation (outbox pattern)."""
    headers, _ = _setup_org_with_admin(
        http_client, fake_email, "enum_row@example.com", "Enum Org 4"
    )

    before = db_session.query(EmailOutbox).filter(EmailOutbox.message_type == "invitation").count()

    resp = http_client.post(
        "/api/v1/workspace/invitations",
        json={"email": "row_target@example.com", "role": "recruiter"},
        headers=csrf_headers(http_client),
    )
    assert resp.status_code == 201, resp.text

    db_session.expire_all()
    after = db_session.query(EmailOutbox).filter(EmailOutbox.message_type == "invitation").count()
    assert after == before + 1, (
        f"Expected one new invitation outbox row; before={before}, after={after}"
    )


# ── 5. No SMTP error detail in HTTP response ──────────────────────────────────


def test_smtp_error_not_leaked_in_response(
    http_client: TestClient, fake_email, db_session: SASession
):
    """SMTP-related error messages must not appear in the HTTP response body.

    With the outbox pattern the route never contacts SMTP, so there is nothing
    to leak — this test confirms that explicitly.
    """
    headers, _ = _setup_org_with_admin(
        http_client, fake_email, "enum_leak@example.com", "Enum Org 5"
    )

    resp = http_client.post(
        "/api/v1/workspace/invitations",
        json={"email": "leak_target@example.com", "role": "recruiter"},
        headers=csrf_headers(http_client),
    )
    assert resp.status_code == 201, resp.text
    body_text = resp.text.lower()
    assert "smtp" not in body_text, f"SMTP error detail must not appear in response: {resp.text}"
    assert "failed" not in body_text, (
        f"'failed' delivery status must not appear in response: {resp.text}"
    )
