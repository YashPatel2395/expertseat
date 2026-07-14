"""FastAPI dependencies for authentication and workspace context.

Authorization model: database-backed validation on every request.

JWT claims identify records; the database is the authorization authority.
Role and membership state are derived from the DB, not from JWT claims alone,
so that revocation and role changes take effect immediately without waiting
for the access token to expire.

Dependency chain:
  get_current_user()        — validates JWT, then verifies session/user in DB
    └── get_workspace_context() — verifies membership and org from DB
          └── require_role("admin") — enforces minimum role
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import jwt
from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.tokens import decode_access_token
from app.database import get_db
from app.models.organization import Membership, Organization
from app.models.session import AuthSession
from app.models.user import User


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
    db: Session = Depends(get_db),
) -> CurrentUser:
    """Validate the JWT and verify the session, user, membership, and org in the DB.

    Authorization steps:
      1. Reject missing/expired/invalid JWT.
      2. Load AuthSession by sid claim; reject if not found, revoked, or expired.
      3. Verify session.user_id matches the sub claim (cross-user mismatch → 401).
      4. Load User; reject if not found, inactive, or unverified.
      5. If the session carries org context: load Membership, verify it belongs
         to this user and this org, and is active. Verify the Organization is active.
         If the membership is gone or disabled, silently demote to no-org context
         so the user remains authenticated but loses workspace access (403 from
         get_workspace_context on any workspace endpoint).
      6. Derive the authoritative role from the current Membership row — never
         from the JWT role claim.

    Raises:
        401 MISSING_TOKEN      — cookie absent
        401 EXPIRED_TOKEN      — JWT signature is valid but exp is in the past
        401 INVALID_TOKEN      — any other JWT validation failure
        401 SESSION_INVALID    — session not found, revoked, expired, or mismatched user
        401 ACCOUNT_INVALID    — user not found, inactive, or unverified
    """
    if not es_access:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "MISSING_TOKEN", "message": "Authentication required"},
        )

    try:
        payload = decode_access_token(es_access)
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "EXPIRED_TOKEN", "message": "Access token has expired"},
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "INVALID_TOKEN", "message": "Invalid access token"},
        )

    try:
        claimed_user_id: str = payload["sub"]
        claimed_session_id: str = payload["sid"]
        jti: str = payload["jti"]
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "INVALID_TOKEN", "message": f"Token missing claim: {exc}"},
        ) from exc

    # ── Step 2–3: Validate session in DB ──────────────────────────────────────
    session = (
        db.query(AuthSession)
        .filter(
            AuthSession.id == claimed_session_id,
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > datetime.now(tz=UTC),
        )
        .first()
    )
    if not session or session.user_id != claimed_user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "SESSION_INVALID", "message": "Session is invalid or has expired"},
        )

    # ── Step 4: Validate user in DB ───────────────────────────────────────────
    user = (
        db.query(User)
        .filter(
            User.id == claimed_user_id,
            User.is_active.is_(True),
            User.email_verified.is_(True),
        )
        .first()
    )
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "ACCOUNT_INVALID", "message": "Account is invalid or disabled"},
        )

    # ── Step 5–6: Derive authoritative org context from DB ────────────────────
    org_id = ""
    membership_id = ""
    role = ""

    if session.org_id and session.membership_id:
        membership = (
            db.query(Membership)
            .filter(
                Membership.id == session.membership_id,
                Membership.user_id == claimed_user_id,
                Membership.org_id == session.org_id,
                Membership.is_active.is_(True),
            )
            .first()
        )
        if membership:
            org = (
                db.query(Organization)
                .filter(
                    Organization.id == session.org_id,
                    Organization.is_active.is_(True),
                )
                .first()
            )
            if org:
                org_id = membership.org_id
                membership_id = membership.id
                role = membership.role  # authoritative from DB, not JWT

    return CurrentUser(
        user_id=user.id,
        session_id=session.id,
        org_id=org_id,
        membership_id=membership_id,
        role=role,
        jti=jti,
    )


async def get_workspace_context(
    user: CurrentUser = Depends(get_current_user),
) -> WorkspaceContext:
    """Return the authenticated user's workspace context.

    Raises 403 NO_ACTIVE_WORKSPACE when the session carries no org context.
    This occurs when:
      - The user has no active memberships
      - All memberships were disabled or removed
      - The session's membership was disabled after login

    In all cases the user remains authenticated (get_current_user succeeds)
    but workspace-scoped endpoints are gated here.
    """
    if not user.org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "NO_ACTIVE_WORKSPACE",
                "message": ("No active workspace. Please create or join an organization first."),
            },
        )
    return user
