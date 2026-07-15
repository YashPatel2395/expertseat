"""Integration tests for account-disable session policy.

Invariants verified:
  1. disable_user_account revokes all active sessions immediately
  2. Disabled user cannot use access token (get_current_user rejects)
  3. Refresh for disabled account triggers family revocation + 401 ACCOUNT_DISABLED
  4. enable_user_account does NOT restore old sessions (user must re-login)
  5. Re-enabled user can sign in and get new sessions
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session as SASession

from app.models.session import AuthSession
from app.models.user import User
from tests.integration.conftest import csrf_headers, login, register_and_verify

pytestmark = pytest.mark.integration

_PASSWORD = "TestPassword123!"


def _count_active_sessions(db: SASession, user_id: str) -> int:
    return (
        db.query(AuthSession)
        .filter(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
        .count()
    )


# ── 1. disable_user_account revokes all sessions ──────────────────────────────


def test_disable_user_account_revokes_all_sessions(
    http_client: TestClient, fake_email, db_session: SASession
):
    """disable_user_account must bulk-revoke all active sessions immediately."""
    email = "disable1@example.com"
    register_and_verify(http_client, fake_email, email, password=_PASSWORD)
    login(http_client, email, password=_PASSWORD)

    user = db_session.query(User).filter(User.email == email).first()
    assert user is not None

    db_session.expire_all()
    before_count = _count_active_sessions(db_session, user.id)
    assert before_count >= 1

    from app.services.auth import disable_user_account

    disable_user_account(db_session, user.id, user.id, None)  # actor = self for test simplicity
    db_session.flush()

    db_session.expire_all()
    after_count = _count_active_sessions(db_session, user.id)
    assert after_count == 0, (
        f"Expected 0 active sessions after account disable, found {after_count}"
    )

    db_session.expire_all()
    user_fresh = db_session.query(User).filter(User.email == email).first()
    assert user_fresh is not None
    assert user_fresh.is_active is False, "User must be marked is_active=False"


# ── 2. Disabled user access token rejected ───────────────────────────────────


def test_disabled_account_access_token_rejected(
    http_client: TestClient, fake_email, db_session: SASession
):
    """After disabling, the access token cookie must no longer work."""
    email = "disable2@example.com"
    register_and_verify(http_client, fake_email, email, password=_PASSWORD)
    login(http_client, email, password=_PASSWORD)

    # Verify access works before disable
    resp = http_client.get("/api/v1/auth/me")
    assert resp.status_code == 200

    user = db_session.query(User).filter(User.email == email).first()
    assert user is not None
    user.is_active = False
    db_session.flush()

    # Access token should now be rejected
    resp = http_client.get("/api/v1/auth/me")
    assert resp.status_code == 401, (
        f"Expected 401 for disabled account, got {resp.status_code}: {resp.text}"
    )
    error = resp.json().get("detail", {}).get("error")
    assert error == "ACCOUNT_INVALID", f"Expected ACCOUNT_INVALID, got {error!r}"


# ── 3. Refresh for disabled account revokes family + returns 401 ──────────────


def test_refresh_for_disabled_account_revokes_family_and_returns_401(
    http_client: TestClient, fake_email, db_session: SASession
):
    """When disabled user tries to refresh, family must be revoked and 401 returned."""
    email = "disable3@example.com"
    register_and_verify(http_client, fake_email, email, password=_PASSWORD)
    login(http_client, email, password=_PASSWORD)

    user = db_session.query(User).filter(User.email == email).first()
    assert user is not None
    user_id = user.id

    # Count sessions before
    db_session.expire_all()
    before_count = _count_active_sessions(db_session, user_id)
    assert before_count >= 1

    # Disable the user (do NOT revoke sessions — simulate the case where
    # an admin disables a user via a different mechanism without touching sessions)
    user.is_active = False
    db_session.flush()

    # Now attempt refresh — this should hit RefreshAccountDisabled path
    resp = http_client.post("/api/v1/auth/refresh", headers=csrf_headers(http_client))
    assert resp.status_code == 401, (
        f"Expected 401 for disabled account on refresh, got {resp.status_code}: {resp.text}"
    )
    error = resp.json().get("detail", {}).get("error")
    assert error == "ACCOUNT_DISABLED", f"Expected ACCOUNT_DISABLED, got {error!r}"

    # Family must be revoked — committed by the route handler
    db_session.expire_all()
    after_count = _count_active_sessions(db_session, user_id)
    assert after_count == 0, (
        f"Expected 0 active sessions after disabled-account refresh, found {after_count}"
    )


# ── 4. enable_user_account does NOT restore old sessions ──────────────────────


def test_enable_user_account_does_not_restore_sessions(
    http_client: TestClient, fake_email, db_session: SASession
):
    """Re-enabling a user does not restore their revoked sessions."""
    email = "disable4@example.com"
    register_and_verify(http_client, fake_email, email, password=_PASSWORD)
    login(http_client, email, password=_PASSWORD)

    user = db_session.query(User).filter(User.email == email).first()
    assert user is not None
    user_id = user.id

    from app.services.auth import disable_user_account, enable_user_account

    # Disable — revokes all sessions
    disable_user_account(db_session, user_id, user_id, None)
    db_session.flush()
    db_session.expire_all()
    assert _count_active_sessions(db_session, user_id) == 0

    # Re-enable
    enable_user_account(db_session, user_id, user_id, None)
    db_session.flush()
    db_session.expire_all()

    # Sessions must still be 0 — re-enabling does NOT restore sessions
    still_zero = _count_active_sessions(db_session, user_id)
    assert still_zero == 0, (
        f"Re-enabling must not restore sessions; found {still_zero} active sessions"
    )

    # User must be active again
    user_fresh = db_session.query(User).filter(User.email == email).first()
    assert user_fresh is not None
    assert user_fresh.is_active is True


# ── 5. Re-enabled user can sign in ────────────────────────────────────────────


def test_re_enabled_user_can_sign_in(http_client: TestClient, fake_email, db_session: SASession):
    """After re-enabling, the user can create new sessions by signing in."""
    email = "disable5@example.com"
    register_and_verify(http_client, fake_email, email, password=_PASSWORD)

    user = db_session.query(User).filter(User.email == email).first()
    assert user is not None

    from app.services.auth import disable_user_account, enable_user_account

    # Disable without first logging in
    disable_user_account(db_session, user.id, user.id, None)
    db_session.flush()

    # Re-enable
    enable_user_account(db_session, user.id, user.id, None)
    db_session.flush()

    # Login should now succeed
    resp = http_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": _PASSWORD},
    )
    assert resp.status_code == 200, (
        f"Expected 200 for re-enabled user login, got {resp.status_code}: {resp.text}"
    )
    assert "es_access" in http_client.cookies, "es_access cookie must be set after re-enable login"
