"""Concurrency tests for last-admin protection.

WHY REAL CONCURRENT CONNECTIONS ARE REQUIRED
---------------------------------------------
The standard db_session fixture uses SQLAlchemy's join_transaction_mode="create_savepoint".
Every route-level db.commit() releases a SAVEPOINT rather than committing the outer
transaction.  Two "threads" sharing the same savepoint-wrapped session share the same
outer connection, so they can never race at the DB level — the last-admin guard's
SELECT FOR UPDATE or COUNT(*) check has no cross-thread effect.

To test the real DB-level guard we must:
  1. Commit real data (register, invite, accept) through raw TestClients that bypass
     the savepoint wrapper.
  2. Run two threads, each opening its own TestClient → its own connection/transaction.
  3. Clean up after ourselves since the committed data won't roll back automatically.

We achieve this by registering users and building a two-admin org entirely via HTTP
(using the real database), then firing two concurrent demotion/disable requests and
asserting that at least one admin always survives.
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

_ADMIN1_EMAIL = "last_admin_concurrent_1@example.com"
_ADMIN2_EMAIL = "last_admin_concurrent_2@example.com"
_PASSWORD = "Password123!abc"


# ── Setup / teardown helpers ───────────────────────────────────────────────────


def _register_and_verify(
    client: TestClient,
    fake_email: FakeEmailProvider,
    email: str,
    password: str = _PASSWORD,
    full_name: str = "Test User",
) -> None:
    """Register a user and verify their email via the real DB."""
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": full_name},
    )
    assert resp.status_code == 201, f"Register failed for {email}: {resp.text}"

    sent = fake_email.verification_message_for(email)
    assert sent is not None, f"No verification email received for {email}"
    match = re.search(r"/verify-email\?token=([0-9a-f]{64})", sent.text_body)
    assert match, f"No verification token in email body: {sent.text_body}"

    resp = client.post("/api/v1/auth/verify-email", json={"token": match.group(1)})
    assert resp.status_code == 200, f"Verify failed for {email}: {resp.text}"


def _setup_two_admin_org(
    fake_email: FakeEmailProvider,
) -> tuple[str, str, str]:
    """Set up an org where two users are both admins.

    Flow:
      1. Register + verify admin1  →  admin1's personal org created on registration.
      2. Admin1 invites admin2-email as admin.
      3. Admin2 accepts via accept-new (creates account + joins the org in one call).

    Returns (org_id, admin1_user_id, admin2_user_id).
    Data is committed to the real DB; caller must clean up via _cleanup().
    """
    from app.main import app

    org_id: str = ""
    admin1_user_id: str = ""
    admin2_user_id: str = ""

    # ── Step 1: register admin1 and get their default org ──────────────────────
    with TestClient(app, raise_server_exceptions=False) as c:
        _register_and_verify(c, fake_email, _ADMIN1_EMAIL, full_name="Admin One")

        resp = c.post(
            "/api/v1/auth/login",
            json={"email": _ADMIN1_EMAIL, "password": _PASSWORD},
        )
        assert resp.status_code == 200, f"Admin1 login failed: {resp.text}"
        csrf = c.cookies.get("es_csrf")
        assert csrf, "No es_csrf cookie after admin1 login"

        me = c.get("/api/v1/auth/me")
        assert me.status_code == 200, f"/auth/me failed: {me.text}"
        org_id = me.json()["org_id"]
        admin1_user_id = me.json()["user_id"]

        # ── Step 2: invite admin2 as admin ────────────────────────────────────
        resp = c.post(
            "/api/v1/workspace/invitations",
            json={"email": _ADMIN2_EMAIL, "role": "admin"},
            headers={"X-CSRF-Token": csrf},
        )
        assert resp.status_code == 201, f"Invite failed: {resp.text}"

    # Extract invitation token from the email
    inv_msg = fake_email.invitation_message_for(_ADMIN2_EMAIL)
    assert inv_msg is not None, f"No invitation email received for {_ADMIN2_EMAIL}"
    inv_match = re.search(r"invite/([0-9a-f]{64})", inv_msg.text_body)
    assert inv_match, f"No invite token in invitation email body: {inv_msg.text_body}"
    inv_token = inv_match.group(1)

    # ── Step 3: admin2 accepts via accept-new ──────────────────────────────────
    with TestClient(app, raise_server_exceptions=False) as c2:
        resp = c2.post(
            "/api/v1/workspace/invitations/accept-new",
            json={
                "token": inv_token,
                "full_name": "Admin Two",
                "password": _PASSWORD,
            },
        )
        assert resp.status_code == 201, f"Accept-new failed: {resp.text}"

        me2 = c2.get("/api/v1/auth/me")
        assert me2.status_code == 200, f"Admin2 /auth/me failed: {me2.text}"
        admin2_user_id = me2.json()["user_id"]

    return org_id, admin1_user_id, admin2_user_id


def _setup_single_admin_org(fake_email: FakeEmailProvider) -> tuple[str, str]:
    """Register admin1 only.  Returns (org_id, admin1_user_id)."""
    from app.main import app

    with TestClient(app, raise_server_exceptions=False) as c:
        _register_and_verify(c, fake_email, _ADMIN1_EMAIL, full_name="Solo Admin")

        resp = c.post(
            "/api/v1/auth/login",
            json={"email": _ADMIN1_EMAIL, "password": _PASSWORD},
        )
        assert resp.status_code == 200, f"Solo admin login failed: {resp.text}"

        me = c.get("/api/v1/auth/me")
        assert me.status_code == 200
        return me.json()["org_id"], me.json()["user_id"]


def _cleanup(emails: list[str]) -> None:
    """Delete all orgs these users belong to, then the users themselves.

    Deleting the orgs cascades memberships, invitations, audit events, etc.
    Users are then deleted (cascades auth_sessions, tokens, etc.).
    """
    engine = create_engine(_DATABASE_URL)
    try:
        with engine.connect() as conn:
            for email in emails:
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
            for email in emails:
                conn.execute(
                    text("DELETE FROM users WHERE email = :email"),
                    {"email": email},
                )
            conn.commit()
    finally:
        engine.dispose()


# ── Test 1: concurrent demotions — at least one admin survives ─────────────────


def test_concurrent_demotion_of_different_admins_preserves_one(
    fake_email: FakeEmailProvider,
) -> None:
    """Race: admin1 demotes admin2 AND admin2 demotes admin1 concurrently.

    At least one admin must remain active in the org.  The DB-level guard
    (SELECT COUNT(*) active admins before committing a demotion) ensures that
    both demotions cannot both succeed if there would be no admin left.

    Because each admin is demoting the *other* one (not themselves), both
    requests can in principle succeed while still leaving one admin (the one
    that won the race).  The invariant therefore is: active admin count >= 1
    (not that exactly one request must fail).
    """
    from app.main import app

    try:
        org_id, admin1_user_id, admin2_user_id = _setup_two_admin_org(fake_email)

        barrier = threading.Barrier(2)
        results: list[int] = []
        lock = threading.Lock()

        def demote(actor_email: str, target_user_id: str) -> None:
            with TestClient(app, raise_server_exceptions=False) as c:
                resp = c.post(
                    "/api/v1/auth/login",
                    json={"email": actor_email, "password": _PASSWORD},
                )
                assert resp.status_code == 200, (
                    f"{actor_email} login failed before demotion: {resp.text}"
                )
                csrf = c.cookies.get("es_csrf")

                barrier.wait()

                resp = c.patch(
                    f"/api/v1/workspace/members/{target_user_id}",
                    json={"role": "recruiter"},
                    headers={"X-CSRF-Token": csrf},
                )
                with lock:
                    results.append(resp.status_code)

        t1 = threading.Thread(target=demote, args=(_ADMIN1_EMAIL, admin2_user_id), daemon=True)
        t2 = threading.Thread(target=demote, args=(_ADMIN2_EMAIL, admin1_user_id), daemon=True)
        t1.start()
        t2.start()
        t1.join(timeout=30)
        t2.join(timeout=30)

        assert len(results) == 2, f"Expected 2 results, got {results}"

        # Verify that at least one admin remains in the real DB
        engine = create_engine(_DATABASE_URL)
        try:
            with engine.connect() as conn:
                result = conn.execute(
                    text("""
                        SELECT COUNT(*) FROM memberships
                        WHERE org_id = :org_id
                          AND role = 'admin'
                          AND is_active = true
                    """),
                    {"org_id": org_id},
                )
                admin_count = result.scalar() or 0
        finally:
            engine.dispose()

        assert admin_count >= 1, (
            f"No active admin left after concurrent demotions; HTTP results were {results}"
        )

    finally:
        _cleanup([_ADMIN1_EMAIL, _ADMIN2_EMAIL])


# ── Test 2: single admin cannot demote themselves ─────────────────────────────


def test_one_admin_demotion_blocked(fake_email: FakeEmailProvider) -> None:
    """A sole admin demoting themselves must receive 409 LAST_ADMIN_PROTECTED."""
    from app.main import app

    try:
        org_id, admin1_user_id = _setup_single_admin_org(fake_email)

        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.post(
                "/api/v1/auth/login",
                json={"email": _ADMIN1_EMAIL, "password": _PASSWORD},
            )
            assert resp.status_code == 200, f"Login failed: {resp.text}"
            csrf = c.cookies.get("es_csrf")

            resp = c.patch(
                f"/api/v1/workspace/members/{admin1_user_id}",
                json={"role": "recruiter"},
                headers={"X-CSRF-Token": csrf},
            )
            assert resp.status_code == 409, f"Expected 409, got {resp.status_code}: {resp.text}"
            assert resp.json()["detail"]["error"] == "LAST_ADMIN_PROTECTED", (
                f"Expected LAST_ADMIN_PROTECTED, got {resp.json()['detail']!r}"
            )

    finally:
        _cleanup([_ADMIN1_EMAIL])


# ── Test 3: single admin cannot disable themselves ────────────────────────────


def test_one_admin_disable_blocked(fake_email: FakeEmailProvider) -> None:
    """A sole admin setting their own is_active=False must get 409 LAST_ADMIN_PROTECTED."""
    from app.main import app

    try:
        org_id, admin1_user_id = _setup_single_admin_org(fake_email)

        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.post(
                "/api/v1/auth/login",
                json={"email": _ADMIN1_EMAIL, "password": _PASSWORD},
            )
            assert resp.status_code == 200, f"Login failed: {resp.text}"
            csrf = c.cookies.get("es_csrf")

            resp = c.patch(
                f"/api/v1/workspace/members/{admin1_user_id}/status",
                json={"is_active": False},
                headers={"X-CSRF-Token": csrf},
            )
            assert resp.status_code == 409, f"Expected 409, got {resp.status_code}: {resp.text}"
            assert resp.json()["detail"]["error"] == "LAST_ADMIN_PROTECTED", (
                f"Expected LAST_ADMIN_PROTECTED, got {resp.json()['detail']!r}"
            )

    finally:
        _cleanup([_ADMIN1_EMAIL])


# ── Test 4: concurrent disables — at least one admin survives ─────────────────


def test_concurrent_disable_preserves_one_admin(fake_email: FakeEmailProvider) -> None:
    """Race: admin1 disables admin2 AND admin2 disables admin1 concurrently.

    After both requests complete, at least one admin membership must remain
    active.  The DB-level guard prevents both disables from both succeeding
    if doing so would leave the org with zero active admins.
    """
    from app.main import app

    try:
        org_id, admin1_user_id, admin2_user_id = _setup_two_admin_org(fake_email)

        barrier = threading.Barrier(2)
        results: list[int] = []
        lock = threading.Lock()

        def disable(actor_email: str, target_user_id: str) -> None:
            with TestClient(app, raise_server_exceptions=False) as c:
                resp = c.post(
                    "/api/v1/auth/login",
                    json={"email": actor_email, "password": _PASSWORD},
                )
                assert resp.status_code == 200, (
                    f"{actor_email} login failed before disable: {resp.text}"
                )
                csrf = c.cookies.get("es_csrf")

                barrier.wait()

                resp = c.patch(
                    f"/api/v1/workspace/members/{target_user_id}/status",
                    json={"is_active": False},
                    headers={"X-CSRF-Token": csrf},
                )
                with lock:
                    results.append(resp.status_code)

        t1 = threading.Thread(target=disable, args=(_ADMIN1_EMAIL, admin2_user_id), daemon=True)
        t2 = threading.Thread(target=disable, args=(_ADMIN2_EMAIL, admin1_user_id), daemon=True)
        t1.start()
        t2.start()
        t1.join(timeout=30)
        t2.join(timeout=30)

        assert len(results) == 2, f"Expected 2 results, got {results}"

        # At least one active admin must survive
        engine = create_engine(_DATABASE_URL)
        try:
            with engine.connect() as conn:
                result = conn.execute(
                    text("""
                        SELECT COUNT(*) FROM memberships
                        WHERE org_id = :org_id
                          AND role = 'admin'
                          AND is_active = true
                    """),
                    {"org_id": org_id},
                )
                admin_count = result.scalar() or 0
        finally:
            engine.dispose()

        assert admin_count >= 1, (
            f"No active admin left after concurrent disables; HTTP results were {results}"
        )

    finally:
        _cleanup([_ADMIN1_EMAIL, _ADMIN2_EMAIL])
