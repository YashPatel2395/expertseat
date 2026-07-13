import re
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.main import app

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


# ─── Liveness ────────────────────────────────────────────────────────────────


def test_liveness(client):
    response = client.get("/api/v1/health/live")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_liveness_exact_body(client):
    """Liveness must return exactly {"status": "ok"} — no extra fields."""
    response = client.get("/api/v1/health/live")
    assert response.json() == {"status": "ok"}


def test_liveness_independent_of_database():
    """Liveness must return 200 even when the database is down."""
    mock_r = MagicMock()
    mock_r.ping.return_value = True
    with (
        patch("app.routers.health.check_database_connection", return_value=False),
        patch("app.routers.health.redis_lib") as mock_redis,
    ):
        mock_redis.from_url.return_value = mock_r
        with TestClient(app) as c:
            response = c.get("/api/v1/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_liveness_independent_of_redis():
    """Liveness must return 200 even when Redis is down."""
    with (
        patch("app.routers.health.check_database_connection", return_value=True),
        patch("app.routers.health.redis_lib") as mock_redis,
    ):
        mock_redis.from_url.return_value.ping.side_effect = Exception("Redis unavailable")
        with TestClient(app) as c:
            response = c.get("/api/v1/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# ─── Readiness ────────────────────────────────────────────────────────────────


def test_readiness_healthy(client):
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert "database" in data["checks"]


def test_readiness_healthy_both_checks_present(client):
    """Readiness must include both 'database' and 'redis' in checks when healthy."""
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 200
    checks = response.json()["checks"]
    assert checks["database"] == "ok"
    assert checks["redis"] == "ok"


def test_readiness_db_down():
    """When database is down: 503, database=unavailable, redis=ok."""
    mock_r = MagicMock()
    mock_r.ping.return_value = True
    with (
        patch("app.routers.health.check_database_connection", return_value=False),
        patch("app.routers.health.redis_lib") as mock_redis,
    ):
        mock_redis.from_url.return_value = mock_r
        with TestClient(app) as c:
            response = c.get("/api/v1/health/ready")
    assert response.status_code == 503
    data = response.json()
    assert data["checks"]["database"] == "unavailable"
    assert data["checks"]["redis"] == "ok"


def test_readiness_redis_down():
    """When Redis is down: 503, redis=unavailable, database=ok."""
    with (
        patch("app.routers.health.check_database_connection", return_value=True),
        patch("app.routers.health.redis_lib") as mock_redis,
    ):
        mock_redis.from_url.return_value.ping.side_effect = Exception("Redis unavailable")
        with TestClient(app) as c:
            response = c.get("/api/v1/health/ready")
    assert response.status_code == 503
    data = response.json()
    assert data["checks"]["redis"] == "unavailable"
    assert data["checks"]["database"] == "ok"


def test_readiness_both_down():
    """When both deps are down: 503, both reported as unavailable."""
    with (
        patch("app.routers.health.check_database_connection", return_value=False),
        patch("app.routers.health.redis_lib") as mock_redis,
    ):
        mock_redis.from_url.return_value.ping.side_effect = Exception("Both unavailable")
        with TestClient(app) as c:
            response = c.get("/api/v1/health/ready")
    assert response.status_code == 503
    data = response.json()
    assert data["checks"]["database"] == "unavailable"
    assert data["checks"]["redis"] == "unavailable"


def test_readiness_no_sensitive_data_in_response():
    """Readiness response must not leak connection strings or credentials."""
    mock_r = MagicMock()
    mock_r.ping.return_value = True
    with (
        patch("app.routers.health.check_database_connection", return_value=False),
        patch("app.routers.health.redis_lib") as mock_redis,
    ):
        mock_redis.from_url.return_value = mock_r
        with TestClient(app) as c:
            response = c.get("/api/v1/health/ready")
    body = response.text
    assert "postgresql://" not in body
    assert "redis://" not in body
    assert "expertseat_dev" not in body


# ─── Request ID ───────────────────────────────────────────────────────────────


def test_request_id_header_present(client):
    """Every response must include an X-Request-ID header."""
    response = client.get("/api/v1/health/live")
    assert "x-request-id" in response.headers


def test_request_id_is_valid_uuid(client):
    """The generated X-Request-ID must be a valid UUID."""
    response = client.get("/api/v1/health/live")
    request_id = response.headers.get("x-request-id", "")
    assert _UUID_RE.match(request_id), f"Not a valid UUID: {request_id!r}"


def test_incoming_valid_uuid_is_preserved(client):
    """If the client sends a valid UUID as X-Request-ID, it must be echoed back."""
    incoming = "550e8400-e29b-41d4-a716-446655440000"
    response = client.get("/api/v1/health/live", headers={"X-Request-ID": incoming})
    assert response.headers.get("x-request-id") == incoming


def test_incoming_malformed_id_is_replaced(client):
    """A malformed X-Request-ID must be replaced with a server-generated UUID."""
    response = client.get("/api/v1/health/live", headers={"X-Request-ID": "not-a-uuid"})
    request_id = response.headers.get("x-request-id", "")
    assert _UUID_RE.match(request_id), f"Expected new UUID, got: {request_id!r}"
    assert request_id != "not-a-uuid"


def test_incoming_oversized_id_is_replaced(client):
    """An oversized X-Request-ID (> 36 chars) must be replaced with a new UUID."""
    oversized = "a" * 100
    response = client.get("/api/v1/health/live", headers={"X-Request-ID": oversized})
    request_id = response.headers.get("x-request-id", "")
    assert _UUID_RE.match(request_id), f"Expected new UUID, got: {request_id!r}"


def test_request_ids_are_independent(client):
    """Two separate requests must receive different X-Request-IDs."""
    r1 = client.get("/api/v1/health/live")
    r2 = client.get("/api/v1/health/live")
    id1 = r1.headers.get("x-request-id")
    id2 = r2.headers.get("x-request-id")
    assert id1 != id2, "Two requests should not share a request ID"
