"""Refresh token rotation and replay-detection tests.

The rotation model creates a new AuthSession row on every refresh and revokes
the predecessor.  The predecessor's hash is preserved so that replaying a
rotated token is detectable.

Tested invariants:
  1.  First refresh issues one valid successor.
  2.  Old refresh token becomes unusable after rotation.
  3.  Replaying the old token triggers REFRESH_TOKEN_REUSED.
  4.  Replay revokes the newest active family member.
  5.  Newest token fails after family revocation.
  6.  Repeated refreshes expose exactly one logical active session.
  7.  Session listing excludes rotated ancestors.
  8.  Logout revokes the current active leaf only.
  9.  Logout-all revokes all families belonging to the user.
  10. Password reset revokes all active sessions.
  11. Raw refresh tokens are never stored; only SHA-256 hashes.
  12. Token hashes are unique across all sessions.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session as SASession

from app.models.session import AuthSession
from app.models.user import User
from tests.integration.conftest import csrf_headers, login, register_and_verify

pytestmark = pytest.mark.integration


def _user_sessions(db: SASession, email: str):
    user = db.query(User).filter(User.email == email).first()
    assert user is not None
    return db.query(AuthSession).filter(AuthSession.user_id == user.id).all()


def _active_sessions(db: SASession, email: str):
    return [s for s in _user_sessions(db, email) if s.revoked_at is None]


# ── 1. First refresh issues one valid successor ────────────────────────────────


def test_first_refresh_creates_one_valid_successor(
    http_client: TestClient, fake_email, db_session: SASession
):
    register_and_verify(http_client, fake_email, "rot1@example.com")
    login(http_client, "rot1@example.com")
    before_active = len(_active_sessions(db_session, "rot1@example.com"))

    resp = http_client.post("/api/v1/auth/refresh")
    assert resp.status_code == 200

    after_active = len(_active_sessions(db_session, "rot1@example.com"))
    assert after_active == before_active  # one active at all times


# ── 2. Old refresh token unusable after rotation ──────────────────────────────


def test_old_refresh_token_unusable_after_rotation(http_client: TestClient, fake_email):
    register_and_verify(http_client, fake_email, "rot2@example.com")
    login(http_client, "rot2@example.com")
    old_refresh = http_client.cookies.get("es_refresh")

    http_client.post("/api/v1/auth/refresh")

    http_client.cookies.set("es_refresh", old_refresh)
    resp = http_client.post("/api/v1/auth/refresh")
    assert resp.status_code == 401


# ── 3. Replaying rotated token triggers REFRESH_TOKEN_REUSED ─────────────────


def test_replay_triggers_refresh_token_reused(http_client: TestClient, fake_email):
    register_and_verify(http_client, fake_email, "rot3@example.com")
    login(http_client, "rot3@example.com")
    old_refresh = http_client.cookies.get("es_refresh")

    http_client.post("/api/v1/auth/refresh")

    http_client.cookies.set("es_refresh", old_refresh)
    resp = http_client.post("/api/v1/auth/refresh")
    assert resp.status_code == 401
    assert resp.json()["detail"]["error"] == "REFRESH_TOKEN_REUSED"


# ── 4. Replay revokes the newest active family member ────────────────────────


def test_replay_revokes_newest_active_session(
    http_client: TestClient, fake_email, db_session: SASession
):
    register_and_verify(http_client, fake_email, "rot4@example.com")
    login(http_client, "rot4@example.com")
    old_refresh = http_client.cookies.get("es_refresh")

    # Rotate once — there is now one active leaf
    http_client.post("/api/v1/auth/refresh")
    new_refresh = http_client.cookies.get("es_refresh")
    assert new_refresh != old_refresh

    active_before_replay = _active_sessions(db_session, "rot4@example.com")
    assert len(active_before_replay) == 1

    # Replay the rotated (old) token
    http_client.cookies.set("es_refresh", old_refresh)
    http_client.post("/api/v1/auth/refresh")

    # All sessions in the family must now be revoked
    active_after_replay = _active_sessions(db_session, "rot4@example.com")
    assert len(active_after_replay) == 0


# ── 5. Newest token fails after family revocation ─────────────────────────────


def test_newest_token_fails_after_family_revocation(http_client: TestClient, fake_email):
    register_and_verify(http_client, fake_email, "rot5@example.com")
    login(http_client, "rot5@example.com")
    old_refresh = http_client.cookies.get("es_refresh")

    # Rotate: we now have a new leaf
    http_client.post("/api/v1/auth/refresh")
    current_refresh = http_client.cookies.get("es_refresh")

    # Replay the old token → family revocation
    http_client.cookies.set("es_refresh", old_refresh)
    http_client.post("/api/v1/auth/refresh")

    # Even the current (newest) leaf is now revoked
    http_client.cookies.set("es_refresh", current_refresh)
    resp = http_client.post("/api/v1/auth/refresh")
    assert resp.status_code == 401


# ── 6. Repeated refreshes expose exactly one active session ──────────────────


def test_repeated_refreshes_leave_one_active_session(
    http_client: TestClient, fake_email, db_session: SASession
):
    register_and_verify(http_client, fake_email, "rot6@example.com")
    login(http_client, "rot6@example.com")

    for _ in range(5):
        resp = http_client.post("/api/v1/auth/refresh")
        assert resp.status_code == 200

    active = _active_sessions(db_session, "rot6@example.com")
    assert len(active) == 1, f"Expected 1 active session, got {len(active)}"


# ── 7. Session listing excludes rotated ancestors ─────────────────────────────


def test_session_listing_excludes_rotated_ancestors(
    http_client: TestClient, fake_email
):
    register_and_verify(http_client, fake_email, "rot7@example.com")
    login(http_client, "rot7@example.com")

    # Do several rotations
    for _ in range(3):
        http_client.post("/api/v1/auth/refresh")

    resp = http_client.get("/api/v1/auth/sessions")
    assert resp.status_code == 200
    sessions = resp.json()["sessions"]
    # Only the active leaf should appear
    assert len(sessions) == 1


# ── 8. Logout revokes only the current active leaf ───────────────────────────


def test_logout_revokes_current_active_leaf(
    http_client: TestClient, fake_email, db_session: SASession
):
    register_and_verify(http_client, fake_email, "rot8@example.com")
    login(http_client, "rot8@example.com")
    http_client.post("/api/v1/auth/refresh")

    active_before = _active_sessions(db_session, "rot8@example.com")
    assert len(active_before) == 1

    resp = http_client.post("/api/v1/auth/logout", headers=csrf_headers(http_client))
    assert resp.status_code == 200

    active_after = _active_sessions(db_session, "rot8@example.com")
    assert len(active_after) == 0


# ── 9. Logout-all revokes all families ────────────────────────────────────────


def test_logout_all_revokes_all_families(
    http_client: TestClient, fake_email, db_session: SASession
):
    # Simulate two devices: log in twice (two families)
    register_and_verify(http_client, fake_email, "rot9@example.com")
    login(http_client, "rot9@example.com")
    first_refresh = http_client.cookies.get("es_refresh")

    login(http_client, "rot9@example.com")  # second login = second family

    active_before = _active_sessions(db_session, "rot9@example.com")
    assert len(active_before) == 2

    resp = http_client.post("/api/v1/auth/logout-all", headers=csrf_headers(http_client))
    assert resp.status_code == 200

    active_after = _active_sessions(db_session, "rot9@example.com")
    assert len(active_after) == 0

    # Confirm the first refresh token is also dead
    http_client.cookies.set("es_refresh", first_refresh)
    resp = http_client.post("/api/v1/auth/refresh")
    assert resp.status_code == 401


# ── 10. Password reset revokes all active sessions ───────────────────────────


def test_password_reset_revokes_all_sessions(
    http_client: TestClient, fake_email, db_session: SASession
):
    import re

    register_and_verify(http_client, fake_email, "rot10@example.com")
    login(http_client, "rot10@example.com")

    # Trigger password reset
    http_client.post(
        "/api/v1/auth/forgot-password", json={"email": "rot10@example.com"}
    )
    reset_email = fake_email.password_reset_message_for("rot10@example.com")
    assert reset_email is not None
    m = re.search(r"/reset-password\?token=([0-9a-f]{64})", reset_email.text_body)
    assert m
    token = m.group(1)

    http_client.post(
        "/api/v1/auth/reset-password",
        json={"token": token, "new_password": "NewPassword456!"},
    )

    active = _active_sessions(db_session, "rot10@example.com")
    assert len(active) == 0, "All sessions must be revoked after password reset"


# ── 11. Raw refresh tokens never stored ───────────────────────────────────────


def test_raw_refresh_tokens_never_stored(
    http_client: TestClient, fake_email, db_session: SASession
):
    register_and_verify(http_client, fake_email, "rot11@example.com")
    login(http_client, "rot11@example.com")

    raw_tokens = set()
    for _ in range(3):
        resp = http_client.post("/api/v1/auth/refresh")
        assert resp.status_code == 200
        raw_tokens.add(http_client.cookies.get("es_refresh"))

    user = db_session.query(User).filter(User.email == "rot11@example.com").first()
    assert user is not None
    sessions = db_session.query(AuthSession).filter(AuthSession.user_id == user.id).all()
    stored_hashes = {s.refresh_token_hash for s in sessions}

    for raw in raw_tokens:
        assert raw not in stored_hashes, f"Raw token {raw[:8]}... must not be stored"


# ── 12. Token hashes are unique across all sessions ──────────────────────────


def test_refresh_token_hashes_are_globally_unique(
    http_client: TestClient, fake_email, db_session: SASession
):
    register_and_verify(http_client, fake_email, "rot12@example.com")
    login(http_client, "rot12@example.com")

    for _ in range(4):
        http_client.post("/api/v1/auth/refresh")

    user = db_session.query(User).filter(User.email == "rot12@example.com").first()
    assert user is not None
    sessions = db_session.query(AuthSession).filter(AuthSession.user_id == user.id).all()
    hashes = [s.refresh_token_hash for s in sessions]
    assert len(hashes) == len(set(hashes)), "Each rotation must produce a unique hash"
