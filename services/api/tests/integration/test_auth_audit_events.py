"""Integration tests verifying that auth events write audit records.

Covers:
  1. Successful login writes auth.login_succeeded
  2. Failed login writes auth.login_failed
  3. Logout writes auth.logout
  4. Refresh rotation writes auth.refresh_rotated
  5. Password change writes auth.password_changed
  6. User registration writes user.registered
  7. Email verification writes user.email_verified
"""

import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session as SASession

from app.models.audit import AuditEvent
from app.models.user import User
from tests.integration.conftest import csrf_headers, login, register_and_verify

pytestmark = pytest.mark.integration

_PASSWORD = "TestPassword123!"
_NEW_PASSWORD = "NewPassword456!"


# ── 1. Successful login writes audit ─────────────────────────────────────────


def test_login_success_writes_audit(http_client: TestClient, fake_email, db_session: SASession):
    email = "audit_login_ok@example.com"
    register_and_verify(http_client, fake_email, email, password=_PASSWORD)
    login(http_client, email, password=_PASSWORD)

    user = db_session.query(User).filter(User.email == email).first()
    assert user is not None

    db_session.expire_all()
    events = (
        db_session.query(AuditEvent)
        .filter(
            AuditEvent.event_type == "auth.login_succeeded",
            AuditEvent.actor_id == user.id,
        )
        .all()
    )
    assert len(events) == 1, f"Expected 1 auth.login_succeeded audit event, found {len(events)}"


# ── 2. Failed login writes audit ──────────────────────────────────────────────


def test_login_failure_writes_audit(http_client: TestClient, fake_email, db_session: SASession):
    email = "audit_login_fail@example.com"
    register_and_verify(http_client, fake_email, email, password=_PASSWORD)

    resp = http_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "WrongPassword999!"},
    )
    assert resp.status_code in (401, 429), resp.text

    db_session.expire_all()
    events = db_session.query(AuditEvent).filter(AuditEvent.event_type == "auth.login_failed").all()
    assert len(events) >= 1, (
        f"Expected at least 1 auth.login_failed audit event, found {len(events)}"
    )


# ── 3. Logout writes audit ────────────────────────────────────────────────────


def test_logout_writes_audit(http_client: TestClient, fake_email, db_session: SASession):
    email = "audit_logout@example.com"
    register_and_verify(http_client, fake_email, email, password=_PASSWORD)
    login(http_client, email, password=_PASSWORD)

    user = db_session.query(User).filter(User.email == email).first()
    assert user is not None

    resp = http_client.post("/api/v1/auth/logout", headers=csrf_headers(http_client))
    assert resp.status_code == 200, resp.text

    db_session.expire_all()
    events = (
        db_session.query(AuditEvent)
        .filter(
            AuditEvent.event_type == "auth.logout",
            AuditEvent.actor_id == user.id,
        )
        .all()
    )
    assert len(events) == 1, f"Expected 1 auth.logout audit event, found {len(events)}"


# ── 4. Refresh rotation writes audit ─────────────────────────────────────────


def test_refresh_rotation_writes_audit(http_client: TestClient, fake_email, db_session: SASession):
    email = "audit_refresh@example.com"
    register_and_verify(http_client, fake_email, email, password=_PASSWORD)
    login(http_client, email, password=_PASSWORD)

    user = db_session.query(User).filter(User.email == email).first()
    assert user is not None

    resp = http_client.post("/api/v1/auth/refresh", headers=csrf_headers(http_client))
    assert resp.status_code == 200, resp.text

    db_session.expire_all()
    events = (
        db_session.query(AuditEvent)
        .filter(
            AuditEvent.event_type == "auth.refresh_rotated",
            AuditEvent.actor_id == user.id,
        )
        .all()
    )
    assert len(events) == 1, f"Expected 1 auth.refresh_rotated audit event, found {len(events)}"


# ── 5. Password change writes audit ──────────────────────────────────────────


def test_password_changed_writes_audit(http_client: TestClient, fake_email, db_session: SASession):
    email = "audit_pw_change@example.com"
    register_and_verify(http_client, fake_email, email, password=_PASSWORD)
    login(http_client, email, password=_PASSWORD)

    resp = http_client.post(
        "/api/v1/auth/change-password",
        json={"current_password": _PASSWORD, "new_password": _NEW_PASSWORD},
        headers=csrf_headers(http_client),
    )
    assert resp.status_code == 200, resp.text

    db_session.expire_all()
    user = db_session.query(User).filter(User.email == email).first()
    assert user is not None
    events = (
        db_session.query(AuditEvent)
        .filter(
            AuditEvent.event_type == "auth.password_changed",
            AuditEvent.actor_id == user.id,
        )
        .all()
    )
    assert len(events) == 1, f"Expected 1 auth.password_changed audit event, found {len(events)}"


# ── 6. Registration writes audit ─────────────────────────────────────────────


def test_registration_writes_audit(http_client: TestClient, fake_email, db_session: SASession):
    email = "audit_register@example.com"
    resp = http_client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": _PASSWORD, "full_name": "Audit Test"},
    )
    assert resp.status_code == 201, resp.text

    db_session.expire_all()
    user = db_session.query(User).filter(User.email == email).first()
    assert user is not None
    events = (
        db_session.query(AuditEvent)
        .filter(
            AuditEvent.event_type == "user.registered",
            AuditEvent.actor_id == user.id,
        )
        .all()
    )
    assert len(events) == 1, f"Expected 1 user.registered audit event, found {len(events)}"


# ── 7. Email verification writes audit ───────────────────────────────────────


def test_email_verified_writes_audit(http_client: TestClient, fake_email, db_session: SASession):
    email = "audit_verify@example.com"
    resp = http_client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": _PASSWORD, "full_name": "Audit Verify"},
    )
    assert resp.status_code == 201, resp.text

    sent = fake_email.verification_message_for(email)
    assert sent is not None, f"No verification email found for {email}"
    match = re.search(r"/verify-email\?token=([0-9a-f]{64})", sent.text_body)
    assert match, f"No verification token in email body: {sent.text_body}"
    token = match.group(1)

    resp = http_client.post("/api/v1/auth/verify-email", json={"token": token})
    assert resp.status_code == 200, resp.text

    db_session.expire_all()
    user = db_session.query(User).filter(User.email == email).first()
    assert user is not None
    events = (
        db_session.query(AuditEvent)
        .filter(
            AuditEvent.event_type == "user.email_verified",
            AuditEvent.actor_id == user.id,
        )
        .all()
    )
    assert len(events) == 1, f"Expected 1 user.email_verified audit event, found {len(events)}"
