"""Integration tests for versioned terms and privacy consent on invitation acceptance.

Invariants verified:
  1. Terms and privacy notice acceptance creates a UserConsent row
  2. Missing terms_accepted rejects with 422
  3. Missing privacy_notice_accepted rejects with 422
  4. Unsupported terms version rejects with 422
  5. Unsupported privacy notice version rejects with 422
  6. Consent row stores the exact version strings provided
"""

import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session as SASession

from tests.integration.conftest import csrf_headers, login, register_and_verify

pytestmark = pytest.mark.integration

_PASSWORD = "TestPassword123!"
_NEW_PASSWORD = "NewUserConsent789!"


def _setup_invitation(http_client, fake_email, admin_email, invitee_email, org_name):
    """Register admin, create org, send invitation to invitee_email. Returns token."""
    register_and_verify(http_client, fake_email, admin_email, password=_PASSWORD)
    login(http_client, admin_email, password=_PASSWORD)
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
        headers=headers,
    )
    assert resp.status_code == 200

    headers = csrf_headers(http_client)
    resp = http_client.post(
        "/api/v1/workspace/invitations",
        json={"email": invitee_email, "role": "recruiter"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text

    sent = fake_email.invitation_message_for(invitee_email)
    assert sent is not None
    m = re.search(r"invite/([0-9a-f]{64})", sent.text_body)
    assert m, f"No invite token: {sent.text_body}"
    return m.group(1)


# ── 1. Acceptance creates a UserConsent row ────────────────────────────────────


def test_accept_new_creates_consent_record(
    http_client: TestClient, fake_email, db_session: SASession
):
    from app.main import app
    from app.models.consent import UserConsent
    from app.models.user import User

    admin_email = "consent1_admin@example.com"
    invitee_email = "consent1_invitee@example.com"
    token = _setup_invitation(http_client, fake_email, admin_email, invitee_email, "Consent Org 1")

    with TestClient(app, raise_server_exceptions=True) as c:
        resp = c.post(
            "/api/v1/workspace/invitations/accept-new",
            json={
                "token": token,
                "full_name": "Consent User",
                "password": _NEW_PASSWORD,
                "terms_accepted": True,
                "privacy_notice_accepted": True,
                "terms_version": "2026-07-01",
                "privacy_notice_version": "2026-07-01",
            },
        )
        assert resp.status_code == 201, resp.text

    db_session.expire_all()
    user = db_session.query(User).filter(User.email == invitee_email).first()
    assert user is not None

    consents = db_session.query(UserConsent).filter(UserConsent.user_id == user.id).all()
    assert len(consents) == 1, f"Expected 1 consent record, found {len(consents)}"
    assert consents[0].terms_version == "2026-07-01"
    assert consents[0].privacy_notice_version == "2026-07-01"


# ── 2. Missing terms_accepted rejects ─────────────────────────────────────────


def test_accept_new_missing_terms_accepted_rejects(
    http_client: TestClient, fake_email, db_session: SASession
):
    admin_email = "consent2_admin@example.com"
    invitee_email = "consent2_invitee@example.com"
    token = _setup_invitation(http_client, fake_email, admin_email, invitee_email, "Consent Org 2")

    resp = http_client.post(
        "/api/v1/workspace/invitations/accept-new",
        json={
            "token": token,
            "full_name": "Consent User",
            "password": _NEW_PASSWORD,
            "terms_accepted": False,  # NOT accepted
            "privacy_notice_accepted": True,
            "terms_version": "2026-07-01",
            "privacy_notice_version": "2026-07-01",
        },
    )
    assert resp.status_code == 422, (
        f"Expected 422 when terms not accepted, got {resp.status_code}: {resp.text}"
    )
    error = resp.json().get("detail", {}).get("error")
    assert error == "TERMS_NOT_ACCEPTED", f"Expected TERMS_NOT_ACCEPTED, got {error!r}"


# ── 3. Missing privacy_notice_accepted rejects ────────────────────────────────


def test_accept_new_missing_privacy_accepted_rejects(
    http_client: TestClient, fake_email, db_session: SASession
):
    admin_email = "consent3_admin@example.com"
    invitee_email = "consent3_invitee@example.com"
    token = _setup_invitation(http_client, fake_email, admin_email, invitee_email, "Consent Org 3")

    resp = http_client.post(
        "/api/v1/workspace/invitations/accept-new",
        json={
            "token": token,
            "full_name": "Consent User",
            "password": _NEW_PASSWORD,
            "terms_accepted": True,
            "privacy_notice_accepted": False,  # NOT accepted
            "terms_version": "2026-07-01",
            "privacy_notice_version": "2026-07-01",
        },
    )
    assert resp.status_code == 422, (
        f"Expected 422 when privacy not accepted, got {resp.status_code}: {resp.text}"
    )
    error = resp.json().get("detail", {}).get("error")
    assert error == "PRIVACY_NOT_ACCEPTED", f"Expected PRIVACY_NOT_ACCEPTED, got {error!r}"


# ── 4. Unsupported terms version rejects ──────────────────────────────────────


def test_accept_new_unsupported_terms_version_rejects(
    http_client: TestClient, fake_email, db_session: SASession
):
    admin_email = "consent4_admin@example.com"
    invitee_email = "consent4_invitee@example.com"
    token = _setup_invitation(http_client, fake_email, admin_email, invitee_email, "Consent Org 4")

    resp = http_client.post(
        "/api/v1/workspace/invitations/accept-new",
        json={
            "token": token,
            "full_name": "Consent User",
            "password": _NEW_PASSWORD,
            "terms_accepted": True,
            "privacy_notice_accepted": True,
            "terms_version": "1999-01-01",  # unsupported version
            "privacy_notice_version": "2026-07-01",
        },
    )
    assert resp.status_code == 422, (
        f"Expected 422 for unsupported terms version, got {resp.status_code}: {resp.text}"
    )
    error = resp.json().get("detail", {}).get("error")
    assert error == "UNSUPPORTED_TERMS_VERSION", (
        f"Expected UNSUPPORTED_TERMS_VERSION, got {error!r}"
    )


# ── 5. Unsupported privacy version rejects ────────────────────────────────────


def test_accept_new_unsupported_privacy_version_rejects(
    http_client: TestClient, fake_email, db_session: SASession
):
    admin_email = "consent5_admin@example.com"
    invitee_email = "consent5_invitee@example.com"
    token = _setup_invitation(http_client, fake_email, admin_email, invitee_email, "Consent Org 5")

    resp = http_client.post(
        "/api/v1/workspace/invitations/accept-new",
        json={
            "token": token,
            "full_name": "Consent User",
            "password": _NEW_PASSWORD,
            "terms_accepted": True,
            "privacy_notice_accepted": True,
            "terms_version": "2026-07-01",
            "privacy_notice_version": "2000-01-01",  # unsupported
        },
    )
    assert resp.status_code == 422, (
        f"Expected 422 for unsupported privacy version, got {resp.status_code}: {resp.text}"
    )
    error = resp.json().get("detail", {}).get("error")
    assert error == "UNSUPPORTED_PRIVACY_VERSION", (
        f"Expected UNSUPPORTED_PRIVACY_VERSION, got {error!r}"
    )


# ── 6. Consent row stores exact version strings ────────────────────────────────


def test_accept_new_consent_stores_exact_versions(
    http_client: TestClient, fake_email, db_session: SASession
):
    from app.main import app
    from app.models.consent import UserConsent
    from app.models.user import User

    admin_email = "consent6_admin@example.com"
    invitee_email = "consent6_invitee@example.com"
    token = _setup_invitation(http_client, fake_email, admin_email, invitee_email, "Consent Org 6")

    with TestClient(app, raise_server_exceptions=True) as c:
        resp = c.post(
            "/api/v1/workspace/invitations/accept-new",
            json={
                "token": token,
                "full_name": "Consent Version User",
                "password": _NEW_PASSWORD,
                "terms_accepted": True,
                "privacy_notice_accepted": True,
                "terms_version": "2026-07-01",
                "privacy_notice_version": "2026-07-01",
            },
        )
        assert resp.status_code == 201, resp.text

    db_session.expire_all()
    user = db_session.query(User).filter(User.email == invitee_email).first()
    assert user is not None

    consent = db_session.query(UserConsent).filter(UserConsent.user_id == user.id).first()
    assert consent is not None
    assert consent.terms_version == "2026-07-01", (
        f"Expected terms_version='2026-07-01', got {consent.terms_version!r}"
    )
    assert consent.privacy_notice_version == "2026-07-01", (
        f"Expected privacy_notice_version='2026-07-01', got {consent.privacy_notice_version!r}"
    )
    assert consent.accepted_at is not None, "accepted_at must be set"
