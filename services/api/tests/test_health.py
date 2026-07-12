from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.main import app


def test_liveness(client):
    response = client.get("/api/v1/health/live")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_readiness_healthy(client):
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert "database" in data["checks"]


def test_readiness_db_down():
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
    assert response.json()["checks"]["database"] == "unavailable"
