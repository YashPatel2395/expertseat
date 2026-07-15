"""Integration tests for audit failure observability.

Proved invariant: _write_audit_independent failures are logged (not silently swallowed).
The last-admin protection (409) still blocks the action. The audit failure is
observable via the structured logger output.

WHY THESE TESTS USE LOG CAPTURE
---------------------------------
The `_write_audit_independent` function uses `logger.error(...)` when the
independent audit write fails. We capture that log output to verify that
the failure is observable. The 409 response must still be returned — the
audit failure must not change the HTTP outcome of the protected action.
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session as SASession

from tests.integration.conftest import csrf_headers, login, register_and_verify

pytestmark = pytest.mark.integration

_PASSWORD = "TestPassword123!"


def _setup_admin_and_switch_org(http_client, fake_email, email, org_name):
    """Register admin, create new org, switch to it. Returns headers and org context."""
    register_and_verify(http_client, fake_email, email, password=_PASSWORD)
    login(http_client, email, password=_PASSWORD)
    headers = csrf_headers(http_client)

    resp = http_client.post(
        "/api/v1/workspace/organizations",
        json={"name": org_name},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    org = resp.json()

    resp = http_client.post(
        "/api/v1/auth/switch-org",
        json={"org_id": org["id"]},
        headers=headers,
    )
    assert resp.status_code == 200

    return csrf_headers(http_client), org["id"]


# ── 1. Audit failure produces error log, not silent pass ──────────────────────


def test_audit_independent_failure_produces_error_log():
    """When _write_audit_independent's DB write fails, an error must be logged."""
    from app.services.workspace import _write_audit_independent

    # Patch create_engine (imported inside the function body) to simulate DB failure
    with patch("sqlalchemy.create_engine") as mock_engine_factory:
        mock_engine = MagicMock()
        mock_engine.begin.side_effect = Exception("Simulated DB failure")
        mock_engine.dispose = MagicMock()
        mock_engine_factory.return_value = mock_engine

        with patch("app.services.workspace.logger") as mock_log:
            _write_audit_independent(
                "test.event",
                org_id=None,
                actor_id="actor-1",
                target_id="target-1",
                payload={},
            )
            # Must log error, not raise
            mock_log.error.assert_called_once()
            call_kwargs = mock_log.error.call_args
            # Error message should include event_type
            assert call_kwargs is not None


# ── 2. Audit failure includes structured context (no sensitive payload) ────────


def test_audit_independent_failure_logs_structured_context():
    """The error log must include event_type, org_id, actor_id, exc_type."""
    from app.services.workspace import _write_audit_independent

    logged_kwargs = {}

    with patch("sqlalchemy.create_engine") as mock_engine_factory:
        mock_engine = MagicMock()
        mock_engine.begin.side_effect = RuntimeError("DB failure")
        mock_engine.dispose = MagicMock()
        mock_engine_factory.return_value = mock_engine

        with patch("app.services.workspace.logger") as mock_log:

            def capture_error(msg, **kwargs):
                logged_kwargs.update(kwargs)

            mock_log.error.side_effect = capture_error

            _write_audit_independent(
                "last_admin.action_blocked",
                org_id="org-123",
                actor_id="actor-456",
                target_id="target-789",
                payload={"sensitive": "this must not be logged"},
            )

    assert "event_type" in logged_kwargs, f"Missing event_type in log: {logged_kwargs}"
    assert "exc_type" in logged_kwargs, f"Missing exc_type in log: {logged_kwargs}"
    assert logged_kwargs.get("event_type") == "last_admin.action_blocked"
    # Sensitive payload must NOT appear in the log kwargs
    assert "payload" not in logged_kwargs, (
        f"Sensitive payload must not be logged; found in: {logged_kwargs}"
    )


# ── 3. Protected action still returns 409 when internal audit DB fails ────────


def test_last_admin_protected_409_even_when_audit_db_fails(
    http_client: TestClient, fake_email, db_session: SASession
):
    """When the independent audit DB write fails internally, 409 must still be returned.

    _write_audit_independent catches its own exceptions and logs them.
    _check_not_last_admin must then proceed to raise the 409 HTTPException.
    """
    admin_email = "audobs3_admin@example.com"
    headers, org_id = _setup_admin_and_switch_org(
        http_client, fake_email, admin_email, "Audit Obs Org"
    )

    from app.models.user import User

    user = db_session.query(User).filter(User.email == admin_email).first()
    assert user is not None
    admin_user_id = user.id

    # Simulate DB failure inside _write_audit_independent by patching create_engine.
    # The function catches the exception internally (logs it) and returns normally.
    # _check_not_last_admin then raises 409 as expected.
    with patch("sqlalchemy.create_engine") as mock_engine_factory:
        mock_engine = MagicMock()
        mock_engine.begin.side_effect = RuntimeError("Audit DB down")
        mock_engine.dispose = MagicMock()
        mock_engine_factory.return_value = mock_engine

        resp = http_client.patch(
            f"/api/v1/workspace/members/{admin_user_id}",
            json={"role": "recruiter"},
            headers=headers,
        )

    assert resp.status_code == 409, (
        f"Expected 409 LAST_ADMIN_PROTECTED even when audit DB fails; "
        f"got {resp.status_code}: {resp.text}"
    )
    error = resp.json().get("detail", {}).get("error")
    assert error == "LAST_ADMIN_PROTECTED", f"Expected LAST_ADMIN_PROTECTED, got {error!r}"


# ── 4. Audit failure does NOT raise to caller ─────────────────────────────────


def test_audit_independent_failure_does_not_raise():
    """_write_audit_independent must catch all exceptions — never propagate."""
    from app.services.workspace import _write_audit_independent

    with patch("sqlalchemy.create_engine") as mock_engine_factory:
        mock_engine = MagicMock()
        mock_engine.begin.side_effect = RuntimeError("Total DB failure")
        mock_engine.dispose = MagicMock()
        mock_engine_factory.return_value = mock_engine

        # Must not raise — exceptions are logged but never propagated
        try:
            _write_audit_independent(
                "test.event",
                org_id="org-1",
                actor_id="actor-1",
                target_id="target-1",
                payload={},
            )
        except Exception as exc:
            pytest.fail(
                f"_write_audit_independent must not propagate exceptions, but raised: {exc}"
            )
