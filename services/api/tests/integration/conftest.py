"""Integration test fixtures.

Requirements:
  - DATABASE_URL must point to a real PostgreSQL database (tables created by migration)
  - REDIS_URL must point to a real Redis instance
    Recommendation: set REDIS_URL to redis://localhost:6379/1 (DB 1) in your test
    environment so integration tests do not pollute the default dev DB (DB 0).
  - APP_ENV=test (prevents loading the repo .env file)

These tests are marked @pytest.mark.integration and require real infrastructure.
Run with: uv run pytest tests/integration/ -v

Speed optimization: password_hasher is replaced with a low-cost instance so
that Argon2id does not add 100ms+ per hash in the test suite.

Transaction isolation: db_session uses SQLAlchemy 2.0's
join_transaction_mode="create_savepoint" so that route-level db.commit() calls
commit SAVEPOINTs rather than the outer connection transaction.  The outer
transaction is rolled back at the end of each test without touching the DB.
See docs/TESTING.md for the full explanation.
"""

import os

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as SASession

# ── Monkey-patches (must happen before ANY app import) ─────────────────────────
# Replace the Argon2id hasher with a low-cost instance.  This must occur before
# `from app.auth.crypto import password_hasher` resolves anywhere in the process.
import app.auth.crypto as _crypto_module  # noqa: E402

_crypto_module.password_hasher = PasswordHasher(
    time_cost=1,
    memory_cost=8,
    parallelism=1,
    hash_len=16,
    salt_len=8,
)

from app.database import get_db  # noqa: E402
from app.email.deps import get_email_provider  # noqa: E402
from app.email.fake import FakeEmailProvider  # noqa: E402
from app.main import app  # noqa: E402

# ── Infrastructure URLs ────────────────────────────────────────────────────────

_DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://expertseat:expertseat_dev@localhost:5432/expertseat",
)
# Tests should ideally target Redis DB 1 (set via REDIS_URL=redis://localhost:6379/1).
# Falling back to DB 0 still works; only `rate:*` keys are touched.
_REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")

_engine = create_engine(_DATABASE_URL)

# ── Session-scoped setup ───────────────────────────────────────────────────────


@pytest.fixture(scope="session", autouse=True)
def run_migrations():
    """Ensure all migrations are applied before any integration test runs."""
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(__import__("pathlib").Path(__file__).parent.parent.parent),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.fail(f"Migration failed:\n{result.stderr}")


# ── Per-test database isolation ────────────────────────────────────────────────


@pytest.fixture
def db_session():
    """Database session wrapped in a transaction that rolls back after each test.

    join_transaction_mode="create_savepoint" ensures that route-level db.commit()
    calls release SAVEPOINTs rather than committing the outer connection transaction.
    The outer transaction rolls back at fixture teardown, giving clean isolation
    without truncating tables.
    """
    connection = _engine.connect()
    transaction = connection.begin()
    session = SASession(bind=connection, join_transaction_mode="create_savepoint")

    yield session

    session.close()
    transaction.rollback()
    connection.close()


# ── Per-test Redis rate-limit isolation ────────────────────────────────────────


@pytest.fixture(autouse=True)
def clear_rate_limits():
    """Delete rate-limit counters from Redis before every test.

    All TestClient requests originate from the synthetic IP "testclient".
    Without this fixture, counters accumulate across tests and produce 429s
    after 10 auth requests within a 60-second window.

    Only keys matching the `rate:*` pattern are removed — no other Redis state
    is affected.  For stronger isolation, point REDIS_URL at a dedicated test DB
    (e.g., redis://localhost:6379/1) so the `rate:*` namespace is exclusive to
    the test suite.
    """
    import redis as redis_lib

    r = redis_lib.from_url(_REDIS_URL, decode_responses=True)
    try:
        # SCAN-based deletion is safer than KEYS for large keyspaces.
        # Clears both auth rate-limit keys (rate:*) and invitation rate-limit
        # keys (invite:*) so tests don't interfere with each other.
        to_delete = list(r.scan_iter("rate:*")) + list(r.scan_iter("invite:*"))
        if to_delete:
            r.delete(*to_delete)
    finally:
        r.close()


# ── Email fixture ──────────────────────────────────────────────────────────────


@pytest.fixture
def fake_email():
    """FakeEmailProvider injected via dependency override."""
    provider = FakeEmailProvider()
    app.dependency_overrides[get_email_provider] = lambda: provider
    yield provider
    del app.dependency_overrides[get_email_provider]
    provider.reset()


# ── HTTP client fixture ────────────────────────────────────────────────────────


@pytest.fixture
def http_client(db_session, fake_email):
    """TestClient that uses the transaction-wrapped db_session."""

    def override_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_db
    with TestClient(app, raise_server_exceptions=True) as client:
        yield client
    del app.dependency_overrides[get_db]


# ── Auth helpers ───────────────────────────────────────────────────────────────


def register_and_verify(
    client: TestClient,
    fake_email: FakeEmailProvider,
    email: str,
    password: str = "Password123!",
    full_name: str = "Test User",
) -> dict:
    """Register a user, extract the verification code, verify, and return user info.

    Uses fake_email.verification_message_for() so the helper is robust even when
    other emails (e.g., invitations) have been sent to the same address first.
    """
    import re

    resp = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": full_name},
    )
    assert resp.status_code == 201, resp.text

    sent = fake_email.verification_message_for(email)
    assert sent is not None, f"No verification email found for {email}"
    # Verification emails contain a 64-char hex token in a URL path
    match = re.search(r"/verify-email\?token=([0-9a-f]{64})", sent.text_body)
    assert match, f"No verification token in email body: {sent.text_body}"
    token = match.group(1)

    resp = client.post("/api/v1/auth/verify-email", json={"token": token})
    assert resp.status_code == 200, resp.text

    return {"email": email, "password": password, "full_name": full_name}


def login(client: TestClient, email: str, password: str = "Password123!") -> dict:
    """Log in, assert success, and return the JSON body. Cookies are set on client.

    Access tokens are no longer returned in JSON — they are set only in the
    HttpOnly es_access cookie. Use client.cookies.get("es_access") to check
    that the cookie was set, and GET /auth/me for decoded claim values.
    """
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()


def csrf_headers(client: TestClient) -> dict:
    """Extract CSRF token from cookie and return as header dict."""
    csrf = client.cookies.get("es_csrf")
    assert csrf, "es_csrf cookie not set"
    return {"X-CSRF-Token": csrf}
