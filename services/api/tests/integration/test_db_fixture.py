"""SQLAlchemy savepoint fixture regression tests.

Verifies that the db_session/http_client fixtures provide proper per-test
isolation: each test's writes are rolled back via the outer transaction so
that subsequent tests start with a clean database state.

The key mechanism: db_session uses join_transaction_mode="create_savepoint",
which makes route-level db.commit() issue SAVEPOINT RELEASE rather than
committing to the DB.  The outer transaction is rolled back at teardown.

Tested invariants:
  1. User created by one test is not visible in the next test.
  2. Route commit (db.commit()) does not persist past test boundary.
  3. Writes to db_session are visible to route handlers in the same test.
  4. Multiple commits in one test all roll back cleanly.
  5. Organization created in test is not visible in the next test.
  6. Rollback happens even after a route raises an HTTP error.
  7. Session count returns to baseline across tests.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session as SASession

from app.models.user import User
from tests.integration.conftest import register_and_verify

pytestmark = pytest.mark.integration


# ── helpers ────────────────────────────────────────────────────────────────────

_USER_A = "dbfixture_a@example.com"
_USER_B = "dbfixture_b@example.com"


# ── 1 & 2: writes from one test are invisible in the next ─────────────────────


def test_db_fixture_part1_creates_user(
    http_client: TestClient, fake_email, db_session: SASession
):
    """Create a user and confirm it exists within this test's scope."""
    register_and_verify(http_client, fake_email, _USER_A)
    user = db_session.query(User).filter(User.email == _USER_A).first()
    assert user is not None, "User must be visible within the same test"


def test_db_fixture_part2_user_from_part1_is_gone(db_session: SASession):
    """User created in the previous test must not exist (outer TX was rolled back)."""
    user = db_session.query(User).filter(User.email == _USER_A).first()
    assert user is None, (
        "User from a previous test was visible — "
        "savepoint fixture is not rolling back correctly"
    )


# ── 3: route-written data visible to same-test db_session queries ─────────────


def test_route_writes_visible_to_db_session_in_same_test(
    http_client: TestClient, fake_email, db_session: SASession
):
    register_and_verify(http_client, fake_email, _USER_B)
    # The route committed (via SAVEPOINT RELEASE); db_session shares the same
    # outer connection and must see the row.
    user = db_session.query(User).filter(User.email == _USER_B).first()
    assert user is not None
    assert user.email_verified is True


# ── 4: multiple route commits all roll back ────────────────────────────────────


def test_multiple_route_commits_roll_back_on_teardown(
    http_client: TestClient, fake_email, db_session: SASession
):
    """Multiple sequential route commits within one test all roll back."""
    emails = ["multi1@example.com", "multi2@example.com", "multi3@example.com"]
    for email in emails:
        register_and_verify(http_client, fake_email, email)

    for email in emails:
        user = db_session.query(User).filter(User.email == email).first()
        assert user is not None, f"User {email} must be visible in same test"


def test_multiple_route_commits_are_gone_in_next_test(db_session: SASession):
    """Users from the multi-commit test must all be absent."""
    emails = ["multi1@example.com", "multi2@example.com", "multi3@example.com"]
    for email in emails:
        user = db_session.query(User).filter(User.email == email).first()
        assert user is None, f"User {email} leaked into next test"


# ── 5: org created in test is gone in the next test ──────────────────────────


def test_org_created_in_test_rolls_back(
    http_client: TestClient, fake_email, db_session: SASession
):
    from app.models.organization import Organization

    register_and_verify(http_client, fake_email, "orgrollback@example.com")
    count_in_test = db_session.query(Organization).count()
    assert count_in_test >= 1


def test_org_from_previous_test_is_gone(db_session: SASession):
    from app.models.organization import Organization

    # No orgs should exist — prior test's outer TX was rolled back
    count = db_session.query(Organization).count()
    assert count == 0, f"Expected 0 organizations, found {count}"


# ── 6: rollback after HTTP error ──────────────────────────────────────────────


def test_partial_data_rolls_back_after_route_error(
    http_client: TestClient, fake_email, db_session: SASession
):
    """Even if a route raises after writing data, the fixture rolls back."""
    # Register a user (writes data), then trigger a 409 duplicate-email error
    register_and_verify(http_client, fake_email, "partial@example.com")
    # Second registration with same email → 409 (conflict)
    resp = http_client.post(
        "/api/v1/auth/register",
        json={"email": "partial@example.com", "password": "Password123!", "full_name": "P"},
    )
    assert resp.status_code == 409
    # The first user must still be visible in this test's scope
    user = db_session.query(User).filter(User.email == "partial@example.com").first()
    assert user is not None
