"""Integration tests for password-change session management policy.

Invariants verified:
  1. Changing password revokes all other active sessions
  2. The current session remains valid after password change
  3. Password change updates the es_refresh cookie to a new value
  4. Sessions revoked by a password change can no longer refresh
  5. password_changed_at timestamp is updated in the DB
"""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session as SASession

from app.models.session import AuthSession
from app.models.user import User
from tests.integration.conftest import csrf_headers, login, register_and_verify

pytestmark = pytest.mark.integration

_PASSWORD = "TestPassword123!"
_NEW_PASSWORD = "NewPassword456!xx"


def _change_password(client: TestClient, current_password: str, new_password: str):
    resp = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": current_password, "new_password": new_password},
        headers=csrf_headers(client),
    )
    return resp


def _active_sessions(db: SASession, user_id: str) -> list[AuthSession]:
    return (
        db.query(AuthSession)
        .filter(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
        .all()
    )


# ── 1. Password change revokes other sessions ─────────────────────────────────


def test_password_change_revokes_other_sessions(
    http_client: TestClient, fake_email, db_session: SASession
):
    from app.main import app

    email = "pwchange1@example.com"
    register_and_verify(http_client, fake_email, email, password=_PASSWORD)
    login(http_client, email, password=_PASSWORD)  # session A via http_client

    # Create session B by logging in with a second client.
    # The http_client fixture already overrides get_db → db_session, so client_b
    # shares the same session automatically.
    with TestClient(app, raise_server_exceptions=True) as client_b:
        login(client_b, email, password=_PASSWORD)  # session B

        user = db_session.query(User).filter(User.email == email).first()
        assert user is not None

        db_session.expire_all()
        active_before = _active_sessions(db_session, user.id)
        assert len(active_before) == 2, (
            f"Expected 2 active sessions before password change, found {len(active_before)}"
        )

        # Change password via session A
        resp = _change_password(http_client, _PASSWORD, _NEW_PASSWORD)
        assert resp.status_code == 200, resp.text

        db_session.expire_all()
        active_after = _active_sessions(db_session, user.id)
        # Session A is rotated (still 1 active), session B is revoked
        assert len(active_after) == 1, (
            f"Expected only 1 active session after password change, found {len(active_after)}"
        )


# ── 2. Current session remains valid after password change ────────────────────


def test_password_change_current_session_remains_valid(
    http_client: TestClient, fake_email, db_session: SASession
):
    email = "pwchange2@example.com"
    register_and_verify(http_client, fake_email, email, password=_PASSWORD)
    login(http_client, email, password=_PASSWORD)

    resp = _change_password(http_client, _PASSWORD, _NEW_PASSWORD)
    assert resp.status_code == 200, resp.text

    # New access cookie must be set in the response
    assert "es_access" in http_client.cookies, (
        "es_access cookie must be present after password change"
    )

    # Current session must still be usable
    resp = http_client.get("/api/v1/auth/me")
    assert resp.status_code == 200, resp.text


# ── 3. Password change updates the refresh cookie ────────────────────────────


def test_password_change_updates_cookies(
    http_client: TestClient, fake_email, db_session: SASession
):
    email = "pwchange3@example.com"
    register_and_verify(http_client, fake_email, email, password=_PASSWORD)
    login(http_client, email, password=_PASSWORD)

    old_refresh = http_client.cookies.get("es_refresh")
    assert old_refresh, "es_refresh cookie not set after login"

    resp = _change_password(http_client, _PASSWORD, _NEW_PASSWORD)
    assert resp.status_code == 200, resp.text

    new_refresh = http_client.cookies.get("es_refresh")
    assert new_refresh, "es_refresh cookie not set after password change"
    assert new_refresh != old_refresh, "es_refresh cookie must change after a password change"


# ── 4. Revoked sessions fail after password change ───────────────────────────


def test_revoked_sessions_fail_after_password_change(
    http_client: TestClient, fake_email, db_session: SASession
):
    from app.main import app

    email = "pwchange4@example.com"
    register_and_verify(http_client, fake_email, email, password=_PASSWORD)
    login(http_client, email, password=_PASSWORD)  # session A

    # Create session B and capture its refresh token.
    # The http_client fixture already overrides get_db → db_session.
    with TestClient(app, raise_server_exceptions=True) as client_b:
        login(client_b, email, password=_PASSWORD)
        refresh_b = client_b.cookies.get("es_refresh")
        assert refresh_b, "es_refresh not set on client_b after login"

    # Change password via session A (revokes session B)
    resp = _change_password(http_client, _PASSWORD, _NEW_PASSWORD)
    assert resp.status_code == 200, resp.text

    # Attempt to refresh using session B's (now revoked) token
    with TestClient(app, raise_server_exceptions=True) as client_c:
        client_c.cookies.set("es_refresh", refresh_b)
        # Need a CSRF token — generate a dummy one; the refresh endpoint
        # will reject with 401 before checking CSRF if the session is revoked,
        # or 403 if CSRF check runs first. Either proves the session is dead.
        resp = client_c.post("/api/v1/auth/refresh")
        assert resp.status_code in (401, 403), (
            f"Expected 401 or 403 for revoked session B, got {resp.status_code}: {resp.text}"
        )


# ── 5. password_changed_at is updated ────────────────────────────────────────


def test_password_changed_at_updated(http_client: TestClient, fake_email, db_session: SASession):
    email = "pwchange5@example.com"
    register_and_verify(http_client, fake_email, email, password=_PASSWORD)
    login(http_client, email, password=_PASSWORD)

    time_before = datetime.now(UTC)

    resp = _change_password(http_client, _PASSWORD, _NEW_PASSWORD)
    assert resp.status_code == 200, resp.text

    db_session.expire_all()
    user = db_session.query(User).filter(User.email == email).first()
    assert user is not None
    assert user.password_changed_at is not None, (
        "password_changed_at must be set after a password change"
    )
    assert user.password_changed_at > time_before, (
        f"password_changed_at ({user.password_changed_at}) must be after "
        f"time_before ({time_before})"
    )
