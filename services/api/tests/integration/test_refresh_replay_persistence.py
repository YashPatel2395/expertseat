"""Integration tests proving that refresh token replay revocation persists in the DB.

WHY SEPARATE ENGINE CONNECTIONS ARE REQUIRED
--------------------------------------------
The standard db_session fixture uses SQLAlchemy's join_transaction_mode="create_savepoint".
All route-level db.commit() calls release SAVEPOINTs rather than committing the outer
transaction, so test data is rolled back at fixture teardown without touching the DB.

This isolation model cannot verify that revocation is *actually committed* to the
database — it only proves that revocation is visible within the same connection. These
tests open a brand-new SQLAlchemy engine with an independent connection (no savepoint
wrapper) to confirm that committed state is durable and visible across connections.

Both tests commit real data to the DB and must clean up after themselves in finally blocks.
"""

import os
import re
import threading

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as SASession

from app.email.fake import FakeEmailProvider

pytestmark = pytest.mark.integration

_DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://expertseat:expertseat_dev@localhost:5432/expertseat",
)

_TEST_EMAIL_REPLAY = "replay_persistence@example.com"
_TEST_EMAIL_CONCURRENT = "concurrent_replay_persistence@example.com"
_TEST_PASSWORD = "Password123!abc"
_TEST_NAME = "Replay Persistence Test User"


def _setup_real_user_and_login(
    fake_email: FakeEmailProvider,
    email: str,
    password: str,
    name: str,
) -> tuple[str, str]:
    """Register, verify and log in a user using the real (non-savepoint) DB.

    Returns (refresh_token, csrf_token) as raw cookie values.
    The fake_email dependency override is already set by the fixture; we just
    create a new TestClient that uses the real DB (no savepoint wrapper).
    """
    from app.main import app

    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": password, "full_name": name},
        )
        assert resp.status_code == 201, f"Register failed: {resp.text}"

        sent = fake_email.verification_message_for(email)
        assert sent is not None, "No verification email received"
        match = re.search(r"/verify-email\?token=([0-9a-f]{64})", sent.text_body)
        assert match, f"No verification token in email body: {sent.text_body}"
        verify_token = match.group(1)

        resp = client.post("/api/v1/auth/verify-email", json={"token": verify_token})
        assert resp.status_code == 200, f"Verify failed: {resp.text}"

        resp = client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password},
        )
        assert resp.status_code == 200, f"Login failed: {resp.text}"

        refresh_token = client.cookies.get("es_refresh")
        csrf_token = client.cookies.get("es_csrf")
        assert refresh_token, "No es_refresh cookie after login"
        assert csrf_token, "No es_csrf cookie after login"

    return refresh_token, csrf_token


def _cleanup_real_db(email: str) -> None:
    """Delete the test user, their orgs, and all cascading rows from the real DB.

    Orgs must be deleted explicitly because organizations are not cascade-deleted
    when their members are removed (only memberships cascade from org).
    """
    engine = create_engine(_DATABASE_URL)
    try:
        with engine.connect() as conn:
            from sqlalchemy import text

            conn.execute(
                text("""
                    DELETE FROM organizations
                    WHERE id IN (
                        SELECT m.org_id FROM memberships m
                        JOIN users u ON u.id = m.user_id
                        WHERE u.email = :email
                    )
                """),
                {"email": email},
            )
            conn.execute(text("DELETE FROM users WHERE email = :email"), {"email": email})
            conn.commit()
    finally:
        engine.dispose()


def test_replay_revocation_persists_in_separate_connection(
    fake_email: FakeEmailProvider,
) -> None:
    """Family revocation triggered by replay is durable: visible in a separate DB connection.

    Steps:
    1. Register + login → refresh_token_0, csrf_0
    2. Rotate once → refresh_token_1, csrf_1 (assert 200)
    3. Replay predecessor (refresh_token_0) → assert 401 REFRESH_TOKEN_REUSED
    4. Open a SEPARATE SQLAlchemy engine + session (new connection, independent of TestClient)
    5. Query all AuthSessions for the user — assert ALL are revoked (revoked_at IS NOT NULL)
    6. Try refresh_token_1 (newest) in a fresh TestClient → assert 4xx
    """
    from app.main import app
    from app.models.session import AuthSession
    from app.models.user import User

    try:
        # Step 1: setup real user and login
        refresh_token_0, csrf_0 = _setup_real_user_and_login(
            fake_email, _TEST_EMAIL_REPLAY, _TEST_PASSWORD, _TEST_NAME
        )

        # Step 2: rotate once using a fresh TestClient
        refresh_token_1: str
        csrf_1: str
        with TestClient(app, raise_server_exceptions=False) as client:
            client.cookies.set("es_refresh", refresh_token_0)
            client.cookies.set("es_csrf", csrf_0)
            resp = client.post("/api/v1/auth/refresh", headers={"X-CSRF-Token": csrf_0})
            assert resp.status_code == 200, f"First rotation failed: {resp.text}"
            refresh_token_1 = resp.cookies.get("es_refresh")
            csrf_1 = resp.cookies.get("es_csrf")
            assert refresh_token_1, "No es_refresh cookie after first rotation"
            assert csrf_1, "No es_csrf cookie after first rotation"
            assert refresh_token_1 != refresh_token_0, "Rotation must produce a new token"

        # Step 3: replay the predecessor token → must get REFRESH_TOKEN_REUSED
        with TestClient(app, raise_server_exceptions=False) as client:
            client.cookies.set("es_refresh", refresh_token_0)
            client.cookies.set("es_csrf", csrf_0)
            resp = client.post("/api/v1/auth/refresh", headers={"X-CSRF-Token": csrf_0})
            assert resp.status_code == 401, f"Expected 401 on replay, got {resp.status_code}"
            error = resp.json().get("detail", {}).get("error") or resp.json().get("error")
            assert error == "REFRESH_TOKEN_REUSED", f"Expected REFRESH_TOKEN_REUSED, got: {error}"

        # Step 4 + 5: open a completely separate engine/session to verify committed state
        separate_engine = create_engine(_DATABASE_URL)
        try:
            with SASession(bind=separate_engine.connect()) as db:
                user = db.query(User).filter(User.email == _TEST_EMAIL_REPLAY).first()
                assert user is not None, "User not found in separate DB connection"

                all_sessions = db.query(AuthSession).filter(AuthSession.user_id == user.id).all()
                assert len(all_sessions) > 0, "Expected at least some sessions in DB"

                active_sessions = [s for s in all_sessions if s.revoked_at is None]
                assert len(active_sessions) == 0, (
                    f"Expected ZERO active sessions after replay revocation "
                    f"(separate connection), found {len(active_sessions)} active out of "
                    f"{len(all_sessions)} total"
                )
        finally:
            separate_engine.dispose()

        # Step 6: newest token (refresh_token_1) should also be rejected (family revoked)
        with TestClient(app, raise_server_exceptions=False) as client:
            client.cookies.set("es_refresh", refresh_token_1)
            client.cookies.set("es_csrf", csrf_1)
            resp = client.post("/api/v1/auth/refresh", headers={"X-CSRF-Token": csrf_1})
            assert resp.status_code in (401, 403), (
                f"Expected 401/403 for revoked family member, got {resp.status_code}"
            )

        # Step 7: new TestClient instance, try refresh_token_1 again
        with TestClient(app, raise_server_exceptions=False) as fresh_client:
            fresh_client.cookies.set("es_refresh", refresh_token_1)
            fresh_client.cookies.set("es_csrf", csrf_1)
            resp = fresh_client.post("/api/v1/auth/refresh", headers={"X-CSRF-Token": csrf_1})
            assert resp.status_code in (401, 403), (
                f"Expected 401/403 on second new TestClient attempt, got {resp.status_code}"
            )

    finally:
        _cleanup_real_db(_TEST_EMAIL_REPLAY)


def test_concurrent_replay_leaves_zero_active_sessions(
    fake_email: FakeEmailProvider,
) -> None:
    """After concurrent replay detection, ZERO active sessions remain in the family.

    This replaces the weaker `<= 1` assertion in test_concurrent_refresh.py.
    Two threads attempt to refresh with the same token simultaneously. The winner
    gets 200 and the loser triggers REFRESH_TOKEN_REUSED and family revocation.
    A separate DB connection then confirms that zero active sessions remain.

    Steps:
    1. Register + login → refresh_token, csrf_token
    2. Barrier(2): two threads both POST /auth/refresh with the same token
    3. One thread gets 200, one gets 401 REFRESH_TOKEN_REUSED
    4. Open separate DB connection
    5. Query all sessions for the user
    6. Assert zero active (revoked_at IS NULL) sessions
    """
    from app.main import app
    from app.models.session import AuthSession
    from app.models.user import User

    try:
        refresh_token, csrf_token = _setup_real_user_and_login(
            fake_email, _TEST_EMAIL_CONCURRENT, _TEST_PASSWORD, _TEST_NAME
        )

        barrier = threading.Barrier(2)
        results: list[int] = []
        lock = threading.Lock()

        def do_refresh() -> None:
            # Each thread creates its own TestClient, which in turn opens its own
            # DB connection and transaction — this is what exercises the row lock.
            with TestClient(app, raise_server_exceptions=False) as client:
                client.cookies.set("es_refresh", refresh_token)
                client.cookies.set("es_csrf", csrf_token)
                # Both threads reach the barrier before either fires the request,
                # maximising the chance of a genuine race at the DB level.
                barrier.wait()
                resp = client.post(
                    "/api/v1/auth/refresh",
                    headers={"X-CSRF-Token": csrf_token},
                )
                with lock:
                    results.append(resp.status_code)

        t1 = threading.Thread(target=do_refresh, daemon=True)
        t2 = threading.Thread(target=do_refresh, daemon=True)
        t1.start()
        t2.start()
        t1.join(timeout=30)
        t2.join(timeout=30)

        assert len(results) == 2, f"Expected 2 results, got {results}"

        # Inspect the real DB via a separate independent connection
        separate_engine = create_engine(_DATABASE_URL)
        try:
            with SASession(bind=separate_engine.connect()) as db:
                user = db.query(User).filter(User.email == _TEST_EMAIL_CONCURRENT).first()
                assert user is not None, "User not found in separate DB connection"

                active_sessions = (
                    db.query(AuthSession)
                    .filter(
                        AuthSession.user_id == user.id,
                        AuthSession.revoked_at.is_(None),
                    )
                    .all()
                )
                assert len(active_sessions) == 0, (
                    f"Expected ZERO active sessions after concurrent replay revocation "
                    f"(separate connection), found {len(active_sessions)}"
                )
        finally:
            separate_engine.dispose()

    finally:
        _cleanup_real_db(_TEST_EMAIL_CONCURRENT)
