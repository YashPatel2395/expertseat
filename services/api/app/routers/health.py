import redis as redis_lib
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.config import settings
from app.database import check_database_connection

router = APIRouter(prefix="/health", tags=["health"])


class LivenessResponse(BaseModel):
    status: str


class ReadinessResponse(BaseModel):
    status: str
    checks: dict[str, str]


@router.get("/live", response_model=LivenessResponse)
def liveness():
    return {"status": "ok"}


@router.get("/ready", response_model=ReadinessResponse)
def readiness():
    checks: dict[str, str] = {}
    all_ok = True

    db_ok = check_database_connection()
    checks["database"] = "ok" if db_ok else "unavailable"
    if not db_ok:
        all_ok = False

    _redis_client = None
    try:
        _redis_client = redis_lib.from_url(
            settings.redis_url,
            socket_connect_timeout=settings.redis_connect_timeout,
            socket_timeout=settings.redis_socket_timeout,
        )
        _redis_client.ping()
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "unavailable"
        all_ok = False
    finally:
        if _redis_client is not None:
            try:
                _redis_client.close()
            except Exception:
                pass

    status_code = 200 if all_ok else 503
    return JSONResponse(
        status_code=status_code,
        content={"status": "ready" if all_ok else "degraded", "checks": checks},
    )
