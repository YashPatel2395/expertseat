"""Integration tests for absolute session family expiration.

Invariants verified:
  1. Access token is rejected after family_expires_at (dep check)
  2. Refresh is rejected after family_expires_at
  3. Successor expires_at is capped to family_expires_at when idle TTL > remaining
  4. Session listing excludes families where family_expires_at <= now
  5. Family expiration is enforced on the DB-backed access dep (not just refresh)
  6. Expired families are excluded from list_sessions
  7. change_password caps successor expires_at at family_expires_at
  8. family_expires_at is inherited (never extended) across rotations
"""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session as SASession

from app.models.session import AuthSession
from app.models.user import User
from tests.integration.conftest import csrf_headers, login, register_and_verify

pytestmark = pytest.mark.integration

_PASSWORD = "TestPassword123!"
_NEW_PASSWORD = "NewPassword456!xx"


def _expire_family(db: SASession, session_id: str) -> None:
    """Force a session's family to be expired in the past."""
    past = datetime.now(UTC) - timedelta(seconds=1)
    db.query(AuthSession).filter(AuthSession.id == session_id).update({"family_expires_at": past})
    db.flush()


def _set_family_tight(db: SASession, session_id: str, seconds_remaining: int) -> None:
    """Set family_expires_at to N seconds in the future."""
    tight = datetime.now(UTC) + timedelta(seconds=seconds_remaining)
    db.query(AuthSession).filter(AuthSession.id == session_id).update({"family_expires_at": tight})
    db.flush()


# ── 1. Access token rejected after family_expires_at ─────────────────────────


def test_access_rejected_after_family_expires(
    http_client: TestClient, fake_email, db_session: SASession
):
    """get_current_user must reject tokens from expired families."""
    email = "famexp1@example.com"
    register_and_verify(http_client, fake_email, email, password=_PASSWORD)
    login(http_client, email, password=_PASSWORD)

    me = http_client.get("/api/v1/auth/me")
    assert me.status_code == 200
    session_id = me.json()["session_id"]

    # Expire the family in the DB
    _expire_family(db_session, session_id)

    # Next request with same access token must be rejected
    resp = http_client.get("/api/v1/auth/me")
    assert resp.status_code == 401, (
        f"Expected 401 after family expiration, got {resp.status_code}: {resp.text}"
    )


# ── 2. Refresh rejected after family_expires_at ────────────────────────────────


def test_refresh_rejected_after_family_expires(
    http_client: TestClient, fake_email, db_session: SASession
):
    """refresh_session must reject tokens from expired families."""
    email = "famexp2@example.com"
    register_and_verify(http_client, fake_email, email, password=_PASSWORD)
    login(http_client, email, password=_PASSWORD)

    me = http_client.get("/api/v1/auth/me")
    assert me.status_code == 200
    session_id = me.json()["session_id"]

    _expire_family(db_session, session_id)

    # Attempt refresh — should fail with 401 SESSION_EXPIRED
    resp = http_client.post("/api/v1/auth/refresh", headers=csrf_headers(http_client))
    assert resp.status_code == 401, (
        f"Expected 401 after family expiration on refresh, got {resp.status_code}: {resp.text}"
    )
    error = resp.json().get("detail", {}).get("error")
    assert error == "SESSION_EXPIRED", f"Expected SESSION_EXPIRED, got {error!r}"


# ── 3. Successor expires_at capped at family_expires_at ───────────────────────


def test_successor_expires_at_capped_at_family_expires(
    http_client: TestClient, fake_email, db_session: SASession
):
    """When family expires sooner than idle TTL, successor must use family_expires_at."""
    email = "famexp3@example.com"
    register_and_verify(http_client, fake_email, email, password=_PASSWORD)
    login(http_client, email, password=_PASSWORD)

    me = http_client.get("/api/v1/auth/me")
    assert me.status_code == 200
    session_id = me.json()["session_id"]

    # Set family to expire in 60 seconds (much less than 14-day idle TTL)
    _set_family_tight(db_session, session_id, seconds_remaining=60)

    resp = http_client.post("/api/v1/auth/refresh", headers=csrf_headers(http_client))
    assert resp.status_code == 200, f"Refresh failed: {resp.text}"

    # Look up the new session
    db_session.expire_all()
    user = db_session.query(User).filter(User.email == email).first()
    assert user is not None

    sessions = (
        db_session.query(AuthSession)
        .filter(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
        .all()
    )
    assert len(sessions) == 1, f"Expected 1 active session, found {len(sessions)}"
    new_session = sessions[0]

    # Successor's expires_at must be <= family_expires_at
    assert new_session.expires_at <= new_session.family_expires_at, (
        f"Successor expires_at ({new_session.expires_at}) must not exceed "
        f"family_expires_at ({new_session.family_expires_at})"
    )

    # Successor must expire within ~60 seconds (with small tolerance)
    remaining = (new_session.expires_at - datetime.now(UTC)).total_seconds()
    assert remaining <= 65, (
        f"Successor should expire within 65s (family TTL), but expires in {remaining:.0f}s"
    )


# ── 4. Session listing excludes expired families ──────────────────────────────


def test_list_sessions_excludes_expired_families(
    http_client: TestClient, fake_email, db_session: SASession
):
    """list_sessions must exclude sessions from expired families."""
    email = "famexp4@example.com"
    register_and_verify(http_client, fake_email, email, password=_PASSWORD)
    login(http_client, email, password=_PASSWORD)

    me = http_client.get("/api/v1/auth/me")
    assert me.status_code == 200
    session_id = me.json()["session_id"]

    # Sessions endpoint should show current session
    resp = http_client.get("/api/v1/auth/sessions")
    assert resp.status_code == 200
    assert len(resp.json()["sessions"]) == 1

    # Expire the family
    _expire_family(db_session, session_id)
    db_session.expire_all()

    # list_sessions (service function) must exclude this family
    from app.services.auth import list_sessions

    result = list_sessions(db_session, me.json()["user_id"], session_id)
    assert len(result) == 0, f"Expected 0 sessions after family expiration, found {len(result)}"


# ── 5. Family expiration uses DB value, not JWT claim ─────────────────────────


def test_family_expiration_enforced_by_db_not_jwt(
    http_client: TestClient, fake_email, db_session: SASession
):
    """Access token validity is determined by DB family_expires_at, not JWT exp."""
    email = "famexp5@example.com"
    register_and_verify(http_client, fake_email, email, password=_PASSWORD)
    login(http_client, email, password=_PASSWORD)

    me = http_client.get("/api/v1/auth/me")
    assert me.status_code == 200
    session_id = me.json()["session_id"]

    # JWT itself is still valid (exp not reached), but DB family is expired
    _expire_family(db_session, session_id)

    # Must be rejected even though the JWT exp claim has not elapsed
    resp = http_client.get("/api/v1/auth/me")
    assert resp.status_code == 401, (
        f"Expected 401 (DB-backed family check), got {resp.status_code}: {resp.text}"
    )
    error = resp.json().get("detail", {}).get("error")
    assert error == "SESSION_INVALID", f"Expected SESSION_INVALID, got {error!r}"


# ── 6. Expired families excluded from list_sessions DB query ──────────────────


def test_expired_family_not_counted_as_active(
    http_client: TestClient, fake_email, db_session: SASession
):
    """An unrevoked session in an expired family must not appear as active."""
    email = "famexp6@example.com"
    register_and_verify(http_client, fake_email, email, password=_PASSWORD)
    login(http_client, email, password=_PASSWORD)

    me = http_client.get("/api/v1/auth/me")
    session_id = me.json()["session_id"]
    user_id = me.json()["user_id"]

    # The session is not revoked — it's just in an expired family
    _expire_family(db_session, session_id)
    db_session.expire_all()

    # The session still exists and is NOT revoked
    raw_session = db_session.query(AuthSession).filter(AuthSession.id == session_id).first()
    assert raw_session is not None
    assert raw_session.revoked_at is None, "Session should not be revoked — just family-expired"

    # But list_sessions must not include it
    from app.services.auth import list_sessions

    result = list_sessions(db_session, user_id, session_id)
    assert len(result) == 0, (
        "list_sessions must exclude sessions in expired families even if not explicitly revoked"
    )


# ── 7. change_password caps successor expires_at at family_expires_at ─────────


def test_change_password_caps_successor_expires_at(
    http_client: TestClient, fake_email, db_session: SASession
):
    """Password change must cap successor expires_at at family_expires_at."""
    email = "famexp7@example.com"
    register_and_verify(http_client, fake_email, email, password=_PASSWORD)
    login(http_client, email, password=_PASSWORD)

    me = http_client.get("/api/v1/auth/me")
    session_id = me.json()["session_id"]
    user_id = me.json()["user_id"]

    # Tighten the family to 60 seconds
    _set_family_tight(db_session, session_id, seconds_remaining=60)

    resp = http_client.post(
        "/api/v1/auth/change-password",
        json={"current_password": _PASSWORD, "new_password": _NEW_PASSWORD},
        headers=csrf_headers(http_client),
    )
    assert resp.status_code == 200, resp.text

    db_session.expire_all()
    new_sessions = (
        db_session.query(AuthSession)
        .filter(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
        .all()
    )
    assert len(new_sessions) == 1
    new_s = new_sessions[0]
    assert new_s.expires_at <= new_s.family_expires_at, (
        f"Password-change successor expires_at ({new_s.expires_at}) must not exceed "
        f"family_expires_at ({new_s.family_expires_at})"
    )


# ── 8. family_expires_at never extended across rotations ──────────────────────


def test_family_expires_at_never_extended_across_rotations(
    http_client: TestClient, fake_email, db_session: SASession
):
    """Multiple refresh rotations must never increase family_expires_at."""
    email = "famexp8@example.com"
    register_and_verify(http_client, fake_email, email, password=_PASSWORD)
    login(http_client, email, password=_PASSWORD)

    me = http_client.get("/api/v1/auth/me")
    session_id = me.json()["session_id"]
    user_id = me.json()["user_id"]

    original_session = db_session.query(AuthSession).filter(AuthSession.id == session_id).first()
    assert original_session is not None
    original_family_expires_at = original_session.family_expires_at

    # Rotate once
    resp = http_client.post("/api/v1/auth/refresh", headers=csrf_headers(http_client))
    assert resp.status_code == 200, resp.text

    db_session.expire_all()
    new_sessions = (
        db_session.query(AuthSession)
        .filter(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
        .all()
    )
    assert len(new_sessions) == 1
    rotated_session = new_sessions[0]

    assert rotated_session.family_expires_at == original_family_expires_at, (
        f"family_expires_at must not change after rotation: "
        f"was {original_family_expires_at}, now {rotated_session.family_expires_at}"
    )
