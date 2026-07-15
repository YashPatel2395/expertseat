"""Tests for audit-event atomicity.

Proved invariant: business mutations and their required audit events commit
together.  If the audit INSERT fails, the business mutation must also roll back.

This is the same-transaction audit model chosen for Milestone 1:
  _write_audit() adds AuditEvent to the SQLAlchemy session in the same
  transaction as the business mutation.  db.commit() (releasing the SAVEPOINT
  in tests) commits both together.  If _write_audit() raises before db.commit(),
  neither change reaches the database.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session as SASession

from app.models.organization import Membership
from app.models.user import User
from tests.integration.conftest import csrf_headers, login, register_and_verify

pytestmark = pytest.mark.integration


def _audit_raises(db, org_id, actor_id, target_id, event_type, payload):
    """Drop-in replacement for _write_audit that always raises."""
    raise RuntimeError(f"Simulated audit failure for {event_type}")


# ── 1. Role change rolls back when audit fails ────────────────────────────────


def test_audit_failure_rolls_back_role_change(
    http_client: TestClient, fake_email, db_session: SASession
):
    """Demote a member; if the audit event cannot be written, the role must not change."""
    # Setup: admin in their default org
    register_and_verify(http_client, fake_email, "audit_role@example.com")
    login(http_client, "audit_role@example.com")

    user = db_session.query(User).filter(User.email == "audit_role@example.com").first()
    assert user is not None
    membership = db_session.query(Membership).filter(Membership.user_id == user.id).first()
    assert membership is not None
    assert membership.role == "admin"

    # Patch _write_audit to raise inside the transaction
    with patch("app.services.workspace._write_audit", side_effect=_audit_raises):
        # TestClient has raise_server_exceptions=True; FastAPI 500 may re-raise.
        # Catch any exception to verify DB state regardless.
        try:
            resp = http_client.patch(
                f"/api/v1/workspace/members/{user.id}",
                json={"role": "recruiter"},
                headers=csrf_headers(http_client),
            )
            # If we got here, FastAPI swallowed the error into a 500 response.
            assert resp.status_code == 500
        except Exception:
            # raise_server_exceptions=True caused re-raise — expected behaviour.
            pass

    # The role must still be "admin" — the mutation rolled back with the audit.
    db_session.expire_all()
    membership_after = db_session.query(Membership).filter(Membership.user_id == user.id).first()
    assert membership_after is not None
    assert membership_after.role == "admin", (
        f"Role must not change when audit fails; got {membership_after.role!r}"
    )


# ── 2. Member disable rolls back when audit fails ─────────────────────────────


def test_audit_failure_rolls_back_member_disable(
    http_client: TestClient, fake_email, db_session: SASession
):
    """Disabling a member is rolled back if the audit INSERT fails."""
    register_and_verify(http_client, fake_email, "audit_disable@example.com")
    login(http_client, "audit_disable@example.com")

    user = db_session.query(User).filter(User.email == "audit_disable@example.com").first()
    assert user is not None
    membership = db_session.query(Membership).filter(Membership.user_id == user.id).first()
    assert membership is not None
    assert membership.is_active is True

    with patch("app.services.workspace._write_audit", side_effect=_audit_raises):
        try:
            resp = http_client.patch(
                f"/api/v1/workspace/members/{user.id}/status",
                json={"is_active": False},
                headers=csrf_headers(http_client),
            )
            assert resp.status_code == 500
        except Exception:
            pass

    db_session.expire_all()
    membership_after = db_session.query(Membership).filter(Membership.user_id == user.id).first()
    assert membership_after is not None
    assert membership_after.is_active is True, "Member must remain active when audit fails"


# ── 3. Org settings update rolls back when audit fails ───────────────────────


def test_audit_failure_rolls_back_org_settings_update(
    http_client: TestClient, fake_email, db_session: SASession
):
    """Updating org settings is rolled back if the audit INSERT fails.

    Note on create_organization: that service calls db.flush() before
    _write_audit() to materialise org.id (server-generated UUID).  With the
    savepoint test model, flushed-but-not-committed rows are visible on the
    same connection, so a same-connection rollback check cannot distinguish
    'flush then raise' from 'flush then commit'.  We therefore test the
    update path, which sets Python attributes (no flush) before calling
    _write_audit(), making the rollback detectable on the same connection.
    """
    from app.models.organization import Organization

    register_and_verify(http_client, fake_email, "audit_settings@example.com")
    login(http_client, "audit_settings@example.com")

    me = http_client.get("/api/v1/auth/me").json()
    org_id = me["org_id"]

    # Capture original name
    db_session.expire_all()
    org_before = db_session.query(Organization).filter(Organization.id == org_id).first()
    assert org_before is not None
    original_name = org_before.name

    with patch("app.services.workspace._write_audit", side_effect=_audit_raises):
        try:
            resp = http_client.patch(
                "/api/v1/workspace/settings",
                json={"name": "Audited New Name"},
                headers=csrf_headers(http_client),
            )
            assert resp.status_code == 500
        except Exception:
            pass

    db_session.expire_all()
    org_after = db_session.query(Organization).filter(Organization.id == org_id).first()
    assert org_after is not None
    assert org_after.name == original_name, (
        f"Org name must not change when audit fails; got {org_after.name!r}"
    )


# ── 4. Audit events are not silently dropped ──────────────────────────────────


def test_audit_events_are_written_on_successful_mutation(
    http_client: TestClient, fake_email, db_session: SASession
):
    """Successful business mutations must produce an audit event."""
    from app.models.audit import AuditEvent

    register_and_verify(http_client, fake_email, "audit_success@example.com")
    login(http_client, "audit_success@example.com")

    user = db_session.query(User).filter(User.email == "audit_success@example.com").first()
    assert user is not None

    # Create an extra org (which fires org.created audit event)
    resp = http_client.post(
        "/api/v1/workspace/organizations",
        json={"name": "Audited Org"},
        headers=csrf_headers(http_client),
    )
    assert resp.status_code == 201
    org_id = resp.json()["id"]

    db_session.expire_all()
    audit_events = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.org_id == org_id, AuditEvent.event_type == "org.created")
        .all()
    )
    assert len(audit_events) == 1, f"Expected 1 org.created audit event, found {len(audit_events)}"
