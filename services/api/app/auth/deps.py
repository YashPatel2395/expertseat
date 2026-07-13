"""FastAPI dependencies for authentication and workspace context.

Dependency chain:
  get_current_user()        — validates JWT from es_access cookie
    └── get_workspace_context() — extracts org/role from validated JWT claims
          └── require_role("admin") — enforces minimum role (from policy.py)
"""

from dataclasses import dataclass

import jwt
from fastapi import Cookie, Depends, HTTPException

from app.auth.tokens import decode_access_token


@dataclass(frozen=True)
class CurrentUser:
    user_id: str
    session_id: str
    org_id: str
    membership_id: str
    role: str
    jti: str


# Alias: workspace context is the same object — named for clarity at call sites
WorkspaceContext = CurrentUser


async def get_current_user(
    es_access: str | None = Cookie(None),
) -> CurrentUser:
    """Extract and validate the JWT from the es_access cookie.

    Raises:
        401 MISSING_TOKEN  — cookie absent
        401 EXPIRED_TOKEN  — token is expired
        401 INVALID_TOKEN  — any other JWT validation failure
    """
    if not es_access:
        raise HTTPException(
            status_code=401,
            detail={"error": "MISSING_TOKEN", "message": "Authentication required"},
        )

    try:
        payload = decode_access_token(es_access)
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=401,
            detail={"error": "EXPIRED_TOKEN", "message": "Access token has expired"},
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=401,
            detail={"error": "INVALID_TOKEN", "message": "Invalid access token"},
        )

    try:
        return CurrentUser(
            user_id=payload["sub"],
            session_id=payload["sid"],
            org_id=payload["org"],
            membership_id=payload["mid"],
            role=payload["role"],
            jti=payload["jti"],
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=401,
            detail={"error": "INVALID_TOKEN", "message": f"Token missing claim: {exc}"},
        ) from exc


async def get_workspace_context(
    user: CurrentUser = Depends(get_current_user),
) -> WorkspaceContext:
    """Return the authenticated user's workspace context from JWT claims.

    This is a thin alias of get_current_user provided for semantic clarity
    at workspace-scoped endpoint call sites. The workspace context (org_id,
    membership_id, role) is embedded in the JWT — no DB round-trip required.
    """
    return user
