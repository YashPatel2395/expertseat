"""Redis-backed fixed-window rate limiting for auth endpoints.

Algorithm:
  1. Hash the client IP (SHA-256, truncated to 16 hex chars) to avoid
     storing IP addresses in Redis.
  2. INCR the counter key. On first increment, set TTL = window_seconds.
  3. If count > max_requests: return False (rate limited).
  4. Fail-closed: if Redis is unreachable on an auth endpoint, reject
     the request with 503 rather than allowing unlimited attempts.

Key format:
  rate:{endpoint_group}:{ip_hash_prefix}

This is a FastAPI dependency factory. Usage:
  @router.post("/auth/login")
  async def login(_: None = Depends(auth_rate_limit("login"))): ...
"""

import hashlib

import redis as redis_lib
import structlog
from fastapi import HTTPException, Request

from app.config import settings

logger = structlog.get_logger()


def _ip_hash(ip: str) -> str:
    """One-way hash of an IP address for use as a rate limit key component.

    We store only the first 16 hex chars (64-bit prefix) — enough to be
    unique per IP in practice while not storing the full address.
    """
    return hashlib.sha256(ip.encode()).hexdigest()[:16]


def auth_rate_limit(endpoint_group: str):
    """FastAPI dependency factory for auth endpoint rate limiting.

    Args:
        endpoint_group: Logical name for the endpoint group (e.g. "login").
            Used as part of the Redis key to allow per-group limits.

    Returns a dependency that raises 429 when the rate limit is exceeded,
    or 503 if Redis is unreachable (fail-closed behavior).
    """

    async def _check(request: Request) -> None:
        client_ip = request.client.host if request.client else "unknown"
        ip_prefix = _ip_hash(client_ip)
        key = f"rate:{endpoint_group}:{ip_prefix}"

        try:
            r = redis_lib.from_url(
                settings.redis_url,
                socket_connect_timeout=settings.redis_connect_timeout,
                socket_timeout=settings.redis_socket_timeout,
                decode_responses=True,
            )
            try:
                count = r.incr(key)
                if count == 1:
                    r.expire(key, settings.rate_limit_auth_window)
                if count > settings.rate_limit_auth_max:
                    raise HTTPException(
                        status_code=429,
                        detail={
                            "error": "RATE_LIMITED",
                            "message": "Too many requests. Please try again later.",
                        },
                        headers={"Retry-After": str(settings.rate_limit_auth_window)},
                    )
            finally:
                r.close()
        except HTTPException:
            raise
        except Exception:
            # Fail-closed: Redis unavailable → reject auth requests.
            logger.warning("Redis unavailable for rate limiting", endpoint=endpoint_group)
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "SERVICE_UNAVAILABLE",
                    "message": "Service temporarily unavailable",
                },
            )

    return _check
