"""CSRF protection via double-submit cookie pattern and Origin validation.

All state-mutating endpoints (POST, PUT, PATCH, DELETE) that require
authentication must also depend on require_csrf().

Exemptions (do NOT add require_csrf):
  - GET, HEAD, OPTIONS (read-only)
  - POST /api/v1/auth/login (pre-auth)
  - POST /api/v1/auth/register (pre-auth)
  - POST /api/v1/auth/refresh (guarded by HttpOnly cookie + path restriction)
  - POST /api/v1/auth/forgot-password (pre-auth)
  - POST /api/v1/auth/reset-password (token in body is the credential)
  - POST /api/v1/auth/verify-email (pre-auth)
  - POST /api/v1/auth/resend-verification (pre-auth)
  - POST /api/v1/workspace/invitations/accept (unauthenticated, token in body)
"""

import hmac

from fastapi import Cookie, Header, HTTPException, Request

from app.config import settings

_ALLOWED_ORIGINS = set(settings.cors_allowed_origins)


def _validate_origin(request: Request) -> None:
    """Reject requests from untrusted origins.

    Requests without an Origin header are allowed through — they originate
    from non-browser clients (curl, server-to-server) that cannot be CSRF'd.
    """
    origin = request.headers.get("origin")
    if origin and origin not in _ALLOWED_ORIGINS:
        raise HTTPException(
            status_code=403,
            detail={"error": "ORIGIN_NOT_ALLOWED", "message": "Request origin is not allowed"},
        )


async def require_csrf(
    request: Request,
    x_csrf_token: str | None = Header(None, alias="X-CSRF-Token"),
    es_csrf: str | None = Cookie(None),
) -> None:
    """FastAPI dependency enforcing the double-submit CSRF check.

    Validates:
      1. Origin header is absent or in the allowed list
      2. X-CSRF-Token header matches the es_csrf cookie (constant-time comparison)
    """
    _validate_origin(request)

    if not es_csrf or not x_csrf_token:
        raise HTTPException(
            status_code=403,
            detail={"error": "CSRF_VALIDATION_FAILED", "message": "CSRF token missing"},
        )

    if not hmac.compare_digest(es_csrf, x_csrf_token):
        raise HTTPException(
            status_code=403,
            detail={"error": "CSRF_VALIDATION_FAILED", "message": "CSRF token mismatch"},
        )
