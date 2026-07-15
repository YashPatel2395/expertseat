"""Redis-backed fixed-window rate limiting for auth endpoints.

Algorithm:
  1. Derive a pseudonymous identifier for the client IP using HMAC-SHA256
     with a dedicated rate-limit secret (separate from the JWT signing secret).
     This prevents offline enumeration of IP → key mappings even if Redis
     is compromised.
  2. INCR the counter key. On first increment, set TTL = window_seconds.
  3. If count > max_requests: return 429 with Retry-After = actual remaining TTL.
  4. Fail-closed: if Redis is unreachable on an auth endpoint, reject
     the request with 503 rather than allowing unlimited attempts.

Key format:
  rate:{app_env}:{endpoint_group}:{hmac_prefix}

This is a FastAPI dependency factory. Usage:
  @router.post("/auth/login")
  async def login(_: None = Depends(auth_rate_limit("login"))): ...
"""

import hashlib
import hmac as hmac_lib

import redis as redis_lib
import structlog
from fastapi import HTTPException, Request

from app.config import settings

logger = structlog.get_logger()


def _ip_hmac(ip: str) -> str:
    """Keyed pseudonym for an IP address using HMAC-SHA256.

    Uses `settings.rate_limit_secret` as the key, falling back to
    `settings.secret_key` only in dev/test environments. In production the
    model validator ensures rate_limit_secret is set, so the fallback is
    never reached there. The first 32 hex chars (128 bits) are sufficient
    for unique key-space partitioning in a fixed-window counter.
    """
    secret = settings.rate_limit_secret or settings.secret_key  # fallback only in dev/test
    return hmac_lib.new(secret.encode(), ip.encode(), hashlib.sha256).hexdigest()[:32]


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
        ip_key = _ip_hmac(client_ip)
        key = f"rate:{settings.app_env}:{endpoint_group}:{ip_key}"

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
                    ttl = r.ttl(key)
                    retry_after = str(max(ttl, 1))
                    raise HTTPException(
                        status_code=429,
                        detail={
                            "error": "RATE_LIMITED",
                            "message": "Too many requests. Please try again later.",
                        },
                        headers={"Retry-After": retry_after},
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


def invitation_rate_limit(endpoint_group: str):
    """FastAPI dependency factory for invitation endpoint rate limiting.

    Uses separate limits from auth rate limiting:
      - Configured via rate_limit_invitation_max and rate_limit_invitation_window.
      - Key namespace: "invite:{app_env}:{endpoint_group}:{ip_hmac}"
      - Fail-closed on public endpoints: Redis unavailable → 503.

    Args:
        endpoint_group: Logical name for the invitation endpoint
            (e.g. "invitation-create", "invitation-accept").
    """

    async def _check(request: Request) -> None:
        client_ip = request.client.host if request.client else "unknown"
        ip_key = _ip_hmac(client_ip)
        key = f"invite:{settings.app_env}:{endpoint_group}:{ip_key}"

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
                    r.expire(key, settings.rate_limit_invitation_window)
                if count > settings.rate_limit_invitation_max:
                    ttl = r.ttl(key)
                    retry_after = str(max(ttl, 1))
                    raise HTTPException(
                        status_code=429,
                        detail={
                            "error": "RATE_LIMITED",
                            "message": "Too many requests. Please try again later.",
                        },
                        headers={"Retry-After": retry_after},
                    )
            finally:
                r.close()
        except HTTPException:
            raise
        except Exception:
            # Fail-closed: Redis unavailable → reject invitation requests.
            logger.warning(
                "Redis unavailable for invitation rate limiting", endpoint=endpoint_group
            )
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "SERVICE_UNAVAILABLE",
                    "message": "Service temporarily unavailable",
                },
            )

    return _check
