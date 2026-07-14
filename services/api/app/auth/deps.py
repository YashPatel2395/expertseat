"""FastAPI dependencies for authentication and workspace context.

Dependency chain:
  get_current_user()        — validates JWT from es_access cookie
    └── get_workspace_context() — extracts org/role from validated JWT claims
          └── require_role("admin") — enforces minimum role (from policy.py)
"""

from dataclasses import dataclass

import jwt
from fastapi import Cookie, Depends, HTTPException, status

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

    Raises 403 NO_ACTIVE_WORKSPACE when the JWT carries no org context (org_id
    is empty).  This happens when a user logs in without any active membership —
    for example if all their memberships were disabled.  They can still use
    auth endpoints and create/join an org, but workspace-scoped endpoints are
    gated here.

    The workspace context (org_id, membership_id, role) is embedded in the JWT
    — no DB round-trip is required.
    """
    if not user.org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "NO_ACTIVE_WORKSPACE",
                "message": (
                    "No active workspace. "
                    "Please create or join an organization first."
                ),
            },
        )
    return user
