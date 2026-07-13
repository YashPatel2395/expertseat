import re
import sys
import uuid
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings
from app.routers import health

# ─── Logging configuration ───────────────────────────────────────────────────
# Must be called before any logger is used.

_shared_processors: list[structlog.types.Processor] = [
    structlog.contextvars.merge_contextvars,
    structlog.stdlib.add_log_level,
    structlog.processors.TimeStamper(fmt="iso"),
]

if settings.app_env == "production":
    structlog.configure(
        processors=[
            *_shared_processors,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.PrintLoggerFactory(sys.stdout),
        cache_logger_on_first_use=True,
    )
else:
    structlog.configure(
        processors=[
            *_shared_processors,
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.PrintLoggerFactory(sys.stdout),
        cache_logger_on_first_use=True,
    )

logger = structlog.get_logger()


# ─── Request ID middleware ────────────────────────────────────────────────────


_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Generate a UUID per request, bind it to the structlog context, and return
    it in the X-Request-ID response header.

    If the client sends a valid UUID in X-Request-ID (max 36 chars), that value
    is echoed back. Oversized or malformed values are silently replaced with a
    server-generated UUID.
    """

    async def dispatch(self, request: Request, call_next):
        incoming = request.headers.get("X-Request-ID", "")
        if len(incoming) <= 36 and _UUID_RE.match(incoming):
            request_id = incoming
        else:
            request_id = str(uuid.uuid4())
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


# ─── Application ─────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("ExpertSeat API starting", env=settings.app_env)
    yield
    logger.info("ExpertSeat API shutting down")


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    docs_url="/api/docs" if settings.app_env != "production" else None,
    redoc_url=None,
    lifespan=lifespan,
)

app.add_middleware(RequestIDMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

app.include_router(health.router, prefix=settings.api_v1_prefix)


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    # Log exception type only — never log exc.args or str(exc) which may
    # contain sensitive data (query parameters, internal state, PII).
    logger.error(
        "Unhandled exception",
        path=request.url.path,
        exc_type=type(exc).__name__,
    )
    return JSONResponse(status_code=500, content={"error": "Internal server error"})
