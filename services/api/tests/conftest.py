from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    with (
        patch("app.routers.health.check_database_connection", return_value=True),
        patch("app.routers.health.redis_lib") as mock_redis,
    ):
        mock_r = MagicMock()
        mock_r.ping.return_value = True
        mock_redis.from_url.return_value = mock_r
        from app.main import app

        with TestClient(app) as c:
            yield c
