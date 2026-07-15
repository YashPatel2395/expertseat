"""Concurrency tests for refresh token rotation.

WHY REAL CONCURRENT CONNECTIONS ARE REQUIRED
---------------------------------------------
The standard db_session fixture uses SQLAlchemy's join_transaction_mode="create_savepoint".
Every route-level db.commit() releases a SAVEPOINT rather than committing the outer
transaction, so all test data is rolled back at fixture teardown without touching the DB.

This isolation model is ideal for functional tests, but it fundamentally cannot verify
SELECT FOR UPDATE behaviour: the lock is only meaningful when two *independent*
transactions race to update the same row.  Using the savepoint-wrapped session would
mean both "threads" share the same outer connection and transaction, so they can never
deadlock or block each other — the FOR UPDATE has no cross-thread effect.

To test the real DB-level locking guarantee we must:
  1. Commit real data to the database (bypassing the savepoint wrapper).
  2. Run two threads, each with its own SQLAlchemy connection / transaction.
  3. Clean up after ourselves, since the data is committed and won't roll back.

We achieve this by registering a user via a TestClient that is NOT wired to the
savepoint-wrapped db_session (it uses the real database directly), then firing two
concurrent refresh requests from separate TestClient instances, and finally deleting
the test data in a cleanup block.
"""

import os
import re
import threading

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.email.fake import FakeEmailProvider

pytestmark = pytest.mark.integration

_DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://expertseat:expertseat_dev@localhost:5432/expertseat",
)

_TEST_EMAIL = "concurrent_refresh@example.com"
_TEST_PASSWORD = "Password123!abc"
_TEST_NAME = "Concurrent Test User"


def _setup_real_user_and_login(fake_email: FakeEmailProvider) -> tuple[str, str]:
    """Register, verify and log in a user using the real (non-savepoint) DB.

    Returns (refresh_token, csrf_token) as raw cookie values.
    The fake_email dependency override is already set by the fixture; we just
    create a new TestClient that uses the real DB (no savepoint wrapper).
    """
    from app.main import app

    with TestClient(app, raise_server_exceptions=False) as client:
        # Register
        resp = client.post(
            "/api/v1/auth/register",
            json={
                "email": _TEST_EMAIL,
                "password": _TEST_PASSWORD,
                "full_name": _TEST_NAME,
            },
        )
        assert resp.status_code == 201, f"Register failed: {resp.text}"

        # Extract and use the verification token
        sent = fake_email.verification_message_for(_TEST_EMAIL)
        assert sent is not None, "No verification email received"
        match = re.search(r"/verify-email\?token=([0-9a-f]{64})", sent.text_body)
        assert match, f"No verification token in email body: {sent.text_body}"
        verify_token = match.group(1)

        resp = client.post("/api/v1/auth/verify-email", json={"token": verify_token})
        assert resp.status_code == 200, f"Verify failed: {resp.text}"

        # Login
        resp = client.post(
            "/api/v1/auth/login",
            json={"email": _TEST_EMAIL, "password": _TEST_PASSWORD},
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
    when their members are removed (only memberships cascade from org).  If orgs
    are left behind they leak into test_db_fixture tests that assert a clean DB.
    """
    engine = create_engine(_DATABASE_URL)
    try:
        with engine.connect() as conn:
            # Delete orgs where this user is a member (cascades memberships, invitations, audit)
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
            # Delete the user (cascades auth_sessions, email_verification_tokens, etc.)
            conn.execute(text("DELETE FROM users WHERE email = :email"), {"email": email})
            conn.commit()
    finally:
        engine.dispose()


def test_concurrent_refresh_exactly_one_succeeds(fake_email: FakeEmailProvider) -> None:
    """Two concurrent refresh requests with the same token: exactly one succeeds.

    The SELECT FOR UPDATE in refresh_session() ensures the row is locked by the
    first transaction that reaches it.  The second transaction blocks until the
    first commits (revoking the row), then re-reads revoked_at != NULL and raises
    REFRESH_TOKEN_REUSED.  Exactly one 200 and exactly one 401/403 must result.
    """
    from app.main import app

    try:
        refresh_token, csrf_token = _setup_real_user_and_login(fake_email)

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
        assert results.count(200) == 1, f"Expected exactly 1 successful refresh, got: {results}"
        assert len([s for s in results if s in (401, 403)]) == 1, (
            f"Expected exactly 1 failed refresh (401 or 403), got: {results}"
        )

    finally:
        _cleanup_real_db(_TEST_EMAIL)


def test_concurrent_refresh_no_duplicate_active_descendants(
    fake_email: FakeEmailProvider,
) -> None:
    """After concurrent refresh, at most one active session exists in the family.

    Even if both threads race to the same row, the SELECT FOR UPDATE guarantee
    means only the winner can insert a new active session.  The loser triggers
    family revocation, leaving zero active sessions.  Either way, the total
    number of active (non-revoked) sessions for the family must be ≤ 1.
    """
    from sqlalchemy.orm import Session as SASession

    from app.main import app
    from app.models.session import AuthSession
    from app.models.user import User

    try:
        refresh_token, csrf_token = _setup_real_user_and_login(fake_email)

        barrier = threading.Barrier(2)
        results: list[int] = []
        lock = threading.Lock()

        def do_refresh() -> None:
            with TestClient(app, raise_server_exceptions=False) as client:
                client.cookies.set("es_refresh", refresh_token)
                client.cookies.set("es_csrf", csrf_token)
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

        # Inspect the real DB for active sessions
        engine = create_engine(_DATABASE_URL)
        try:
            with SASession(bind=engine.connect()) as db:
                user = db.query(User).filter(User.email == _TEST_EMAIL).first()
                assert user is not None
                active_sessions = (
                    db.query(AuthSession)
                    .filter(
                        AuthSession.user_id == user.id,
                        AuthSession.revoked_at.is_(None),
                    )
                    .all()
                )
                assert len(active_sessions) <= 1, (
                    f"Expected at most 1 active session after concurrent refresh, "
                    f"found {len(active_sessions)}"
                )
        finally:
            engine.dispose()

    finally:
        _cleanup_real_db(_TEST_EMAIL)
