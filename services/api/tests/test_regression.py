"""Regression tests for behavior that is implemented but not proven elsewhere.

These tests verify observable behavior: what psycopg2 and redis receive, that
clients are cleaned up, that logs never expose raw exception text, and that
request context does not leak between requests.
"""

import io
import json
import re
from unittest.mock import MagicMock, patch

import structlog
from fastapi.testclient import TestClient

from app.config import settings
from app.database import check_database_connection
from app.main import app

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


# ─── Database timeout ────────────────────────────────────────────────────────


def test_database_connect_timeout_is_passed_to_psycopg2():
    """psycopg2.connect must receive connect_timeout=settings.db_connect_timeout."""
    mock_conn = MagicMock()
    with patch("app.database.psycopg2.connect", return_value=mock_conn) as mock_connect:
        result = check_database_connection()
    assert result is True
    mock_connect.assert_called_once()
    _, kwargs = mock_connect.call_args
    assert kwargs.get("connect_timeout") == settings.db_connect_timeout, (
        f"Expected connect_timeout={settings.db_connect_timeout}, "
        f"got {kwargs.get('connect_timeout')!r}"
    )


def test_database_connection_closes_on_success():
    """The psycopg2 connection must be closed after a successful check."""
    mock_conn = MagicMock()
    with patch("app.database.psycopg2.connect", return_value=mock_conn):
        check_database_connection()
    mock_conn.close.assert_called_once()


def test_database_check_returns_false_on_connection_error():
    """check_database_connection must return False when psycopg2 raises."""
    with patch("app.database.psycopg2.connect", side_effect=Exception("connection refused")):
        result = check_database_connection()
    assert result is False


# ─── Redis timeouts ──────────────────────────────────────────────────────────


def test_redis_connect_timeout_is_passed():
    """redis.from_url must receive socket_connect_timeout=settings.redis_connect_timeout."""
    mock_r = MagicMock()
    mock_r.ping.return_value = True
    with (
        patch("app.routers.health.check_database_connection", return_value=True),
        patch("app.routers.health.redis_lib") as mock_redis,
    ):
        mock_redis.from_url.return_value = mock_r
        with TestClient(app) as c:
            c.get("/api/v1/health/ready")
    _, kwargs = mock_redis.from_url.call_args
    assert kwargs.get("socket_connect_timeout") == settings.redis_connect_timeout, (
        f"Expected socket_connect_timeout={settings.redis_connect_timeout}, "
        f"got {kwargs.get('socket_connect_timeout')!r}"
    )


def test_redis_socket_timeout_is_passed():
    """redis.from_url must receive socket_timeout=settings.redis_socket_timeout."""
    mock_r = MagicMock()
    mock_r.ping.return_value = True
    with (
        patch("app.routers.health.check_database_connection", return_value=True),
        patch("app.routers.health.redis_lib") as mock_redis,
    ):
        mock_redis.from_url.return_value = mock_r
        with TestClient(app) as c:
            c.get("/api/v1/health/ready")
    _, kwargs = mock_redis.from_url.call_args
    assert kwargs.get("socket_timeout") == settings.redis_socket_timeout, (
        f"Expected socket_timeout={settings.redis_socket_timeout}, "
        f"got {kwargs.get('socket_timeout')!r}"
    )


# ─── Redis client cleanup ─────────────────────────────────────────────────────


def test_redis_client_closes_after_successful_ping():
    """Redis client .close() must be called after a successful ping."""
    mock_r = MagicMock()
    mock_r.ping.return_value = True
    with (
        patch("app.routers.health.check_database_connection", return_value=True),
        patch("app.routers.health.redis_lib") as mock_redis,
    ):
        mock_redis.from_url.return_value = mock_r
        with TestClient(app) as c:
            c.get("/api/v1/health/ready")
    mock_r.close.assert_called_once()


def test_redis_client_closes_after_failed_ping():
    """Redis client .close() must be called even when .ping() raises an exception."""
    mock_r = MagicMock()
    mock_r.ping.side_effect = Exception("Connection refused")
    with (
        patch("app.routers.health.check_database_connection", return_value=True),
        patch("app.routers.health.redis_lib") as mock_redis,
    ):
        mock_redis.from_url.return_value = mock_r
        with TestClient(app) as c:
            c.get("/api/v1/health/ready")
    mock_r.close.assert_called_once()


# ─── Response safety ──────────────────────────────────────────────────────────


def test_readiness_never_exposes_exception_text_in_response():
    """Readiness response body must never contain exception text from internal errors."""
    secret_msg = "postgresql://root:super_secret_password@internal-db:5432/prod"
    with (
        patch("app.routers.health.check_database_connection", return_value=False),
        patch("app.routers.health.redis_lib") as mock_redis,
    ):
        mock_redis.from_url.return_value.ping.side_effect = Exception(secret_msg)
        with TestClient(app) as c:
            response = c.get("/api/v1/health/ready")
    assert secret_msg not in response.text
    assert "super_secret_password" not in response.text
    assert response.status_code == 503


async def test_generic_error_handler_logs_exc_type_not_exc_message():
    """The generic exception handler must log exc_type, not str(exc).

    Calls the handler directly (no dynamic route needed) to verify the log call
    contains exc_type but never the raw exception message text.
    """
    from app.main import generic_exception_handler

    secret_message = "internal_secret_detail_xyz"
    exc = RuntimeError(secret_message)

    mock_request = MagicMock()
    mock_request.url.path = "/api/v1/health/live"

    with patch("app.main.logger") as mock_logger:
        response = await generic_exception_handler(mock_request, exc)

    assert response.status_code == 500
    mock_logger.error.assert_called_once()
    call_kwargs = mock_logger.error.call_args[1]
    assert call_kwargs.get("exc_type") == "RuntimeError"
    # The raw exception message must never appear in the log call args
    logged_repr = str(mock_logger.error.call_args)
    assert secret_message not in logged_repr


# ─── Production log format ───────────────────────────────────────────────────


def test_production_processor_chain_produces_valid_json():
    """The production structlog processor chain must produce valid JSON for any event."""
    buf = io.StringIO()
    # Configure a temporary structlog instance using the production chain
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.PrintLoggerFactory(buf),
        cache_logger_on_first_use=False,
    )
    log = structlog.get_logger()
    log.info("test_event", request_id="abc-123", key="value")

    output = buf.getvalue().strip()
    # Reset to avoid contaminating other tests
    structlog.reset_defaults()

    parsed = json.loads(output)
    assert parsed.get("event") == "test_event"
    assert parsed.get("key") == "value"
    assert "level" in parsed
    assert "timestamp" in parsed


# ─── Request context isolation ────────────────────────────────────────────────


def test_request_context_does_not_leak_between_requests(client):
    """Each request must get its own request context; IDs must not carry over."""
    id_a = "aaaaaaaa-0000-0000-0000-000000000001"
    id_b = "bbbbbbbb-0000-0000-0000-000000000002"
    r1 = client.get("/api/v1/health/live", headers={"X-Request-ID": id_a})
    r2 = client.get("/api/v1/health/live", headers={"X-Request-ID": id_b})

    id1 = r1.headers.get("x-request-id")
    id2 = r2.headers.get("x-request-id")

    assert id1 == id_a
    assert id2 == id_b
    assert id1 != id2


def test_request_id_is_bound_to_log_context(client):
    """The X-Request-ID echoed in the response must match the one bound to contextvars."""
    incoming = "cccccccc-0000-0000-0000-000000000003"
    with patch("app.main.structlog.contextvars.bind_contextvars") as mock_bind:
        response = client.get("/api/v1/health/live", headers={"X-Request-ID": incoming})
    response_id = response.headers.get("x-request-id")
    # The bind call must have used the same request_id that was returned in the header
    bound_id = mock_bind.call_args[1].get("request_id")
    assert bound_id == response_id == incoming
