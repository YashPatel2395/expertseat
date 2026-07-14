"""Authentication service.

All auth business logic lives here. Route handlers are thin — they validate
input, call service functions, and set cookies. Service functions raise
HTTPException for all error conditions.

Security invariants:
  - Verification tokens: 32 random bytes (256-bit entropy), SHA-256 hash stored.
    Resending invalidates all previous unused tokens for that user.
  - Password reset tokens: 32 random bytes, SHA-256 hash stored, 30-minute TTL.
    A new request invalidates all previous unused reset tokens.
  - Refresh tokens: 32 random bytes, new session row on rotation (old row
    preserved for replay detection).
  - Access tokens: JWT, never returned in JSON — set only in HttpOnly cookie.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.auth.crypto import (
    generate_token_bytes,
    generate_token_hex,
    hash_password,
    needs_rehash,
    sha256_hex,
    verify_password,
)
from app.auth.tokens import create_access_token
from app.config import settings
from app.email.base import EmailProvider
from app.email.templates import email_verification, password_reset
from app.models.organization import Membership
from app.models.session import AuthSession
from app.models.user import EmailVerificationToken, PasswordResetToken, User

# ── Registration ──────────────────────────────────────────────────────────────


def register_user(db: Session, email: str, password: str, full_name: str) -> User:
    """Create a new user account. Raises 409 if email already exists."""
    existing = db.query(User).filter(User.email == email.lower()).first()
    if existing:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "EMAIL_ALREADY_EXISTS",
                "message": "An account with this email already exists",
            },
        )
    user = User(
        email=email.lower(),
        hashed_password=hash_password(password),
        full_name=full_name,
        email_verified=False,
        is_active=True,
    )
    db.add(user)
    db.flush()  # Get user.id without committing
    return user


def create_email_verification_token(db: Session, user_id: str) -> str:
    """Generate a secure verification token, store its hash, return hex token.

    Uses 32 cryptographically random bytes (256-bit entropy).
    All previous unused verification tokens for this user are invalidated
    (marked used) before creating the new one, so resend always supersedes.
    """
    # Invalidate all previous unused tokens for this user
    now = datetime.now(tz=UTC)
    db.query(EmailVerificationToken).filter(
        EmailVerificationToken.user_id == user_id,
        EmailVerificationToken.used_at.is_(None),
        EmailVerificationToken.expires_at > now,
    ).update({"used_at": now})

    token_bytes = generate_token_bytes(32)
    token_hex = token_bytes.hex()
    token_hash = sha256_hex(token_bytes)
    token = EmailVerificationToken(
        user_id=user_id,
        code_hash=token_hash,
        expires_at=now + timedelta(hours=24),
    )
    db.add(token)
    return token_hex


def verify_email_token(db: Session, token_hex: str) -> None:
    """Mark user email as verified. Raises 401 if token is invalid or expired.

    Accepts a 64-character hex token (32 random bytes). Computes SHA-256
    and looks up the matching unused, unexpired record.
    """
    try:
        token_bytes = bytes.fromhex(token_hex)
    except ValueError:
        raise HTTPException(
            status_code=401,
            detail={
                "error": "INVALID_VERIFICATION_TOKEN",
                "message": "Invalid verification link",
            },
        )
    token_hash = sha256_hex(token_bytes)
    record = (
        db.query(EmailVerificationToken)
        .filter(
            EmailVerificationToken.code_hash == token_hash,
            EmailVerificationToken.used_at.is_(None),
            EmailVerificationToken.expires_at > datetime.now(tz=UTC),
        )
        .first()
    )
    if not record:
        raise HTTPException(
            status_code=401,
            detail={
                "error": "INVALID_VERIFICATION_TOKEN",
                "message": "Invalid or expired verification link",
            },
        )
    record.used_at = datetime.now(tz=UTC)
    user = db.query(User).filter(User.id == record.user_id).first()
    if user:
        user.email_verified = True


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.query(User).filter(User.email == email.lower()).first()


# ── Login / Session creation ──────────────────────────────────────────────────


class AuthTokens:
    """Holds the tokens needed to set auth cookies."""

    def __init__(
        self,
        access_token: str,
        refresh_token_hex: str,
        csrf_value: str,
        session_id: str,
    ) -> None:
        self.access_token = access_token
        self.refresh_token_hex = refresh_token_hex
        self.csrf_value = csrf_value
        self.session_id = session_id


def login(
    db: Session,
    email: str,
    password: str,
    ip_address: str,
    user_agent: str | None,
) -> AuthTokens:
    """Authenticate user and create a new auth session.

    Returns AuthTokens with access token, refresh token, and CSRF value.
    Raises 401 on invalid credentials or unverified email.
    """
    user = get_user_by_email(db, email)
    if not user or not verify_password(user.hashed_password, password):
        raise HTTPException(
            status_code=401,
            detail={"error": "INVALID_CREDENTIALS", "message": "Invalid email or password"},
        )
    if not user.email_verified:
        raise HTTPException(
            status_code=401,
            detail={
                "error": "EMAIL_NOT_VERIFIED",
                "message": "Please verify your email before signing in",
            },
        )
    if not user.is_active:
        raise HTTPException(
            status_code=401,
            detail={"error": "ACCOUNT_DISABLED", "message": "This account has been disabled"},
        )

    # Rehash if parameters changed (transparent upgrade)
    if needs_rehash(user.hashed_password):
        user.hashed_password = hash_password(password)

    # Find the user's memberships (prefer most recent org)
    membership = (
        db.query(Membership)
        .filter(Membership.user_id == user.id, Membership.is_active.is_(True))
        .order_by(Membership.created_at.desc())
        .first()
    )

    if not membership:
        org_id = ""
        membership_id = ""
        role = ""
    else:
        org_id = membership.org_id
        membership_id = membership.id
        role = membership.role

    return _create_session(db, user.id, org_id, membership_id, role, ip_address, user_agent)


def _create_session(
    db: Session,
    user_id: str,
    org_id: str,
    membership_id: str,
    role: str,
    ip_address: str,
    user_agent: str | None,
) -> AuthTokens:
    """Create an auth session row and return tokens."""
    refresh_token_bytes = generate_token_bytes(32)
    refresh_token_hex_val = refresh_token_bytes.hex()
    refresh_token_hash = sha256_hex(refresh_token_bytes)
    family_id = str(uuid.uuid4())
    session_id = str(uuid.uuid4())
    ip_hash = hashlib.sha256(ip_address.encode()).hexdigest()
    jti = str(uuid.uuid4())

    expires_at = datetime.now(tz=UTC) + timedelta(seconds=settings.refresh_token_ttl)

    session = AuthSession(
        id=session_id,
        user_id=user_id,
        org_id=org_id or None,
        membership_id=membership_id or None,
        refresh_token_hash=refresh_token_hash,
        family_id=family_id,
        ip_address_hash=ip_hash,
        user_agent=user_agent,
        expires_at=expires_at,
    )
    db.add(session)

    access_token = create_access_token(
        user_id=user_id,
        session_id=session_id,
        org_id=org_id,
        membership_id=membership_id,
        role=role,
        jti=jti,
    )
    csrf_value = generate_token_hex(32)

    return AuthTokens(
        access_token=access_token,
        refresh_token_hex=refresh_token_hex_val,
        csrf_value=csrf_value,
        session_id=session_id,
    )


# ── Token refresh ─────────────────────────────────────────────────────────────


def refresh_session(
    db: Session,
    refresh_token_hex_val: str,
    ip_address: str,
    user_agent: str | None,
) -> AuthTokens:
    """Rotate refresh token and issue new access token.

    Implements family-based replay detection with SELECT FOR UPDATE to prevent
    two concurrent requests from both succeeding on the same token:

    - Token hash matches an active session → acquire row lock, re-check,
      revoke old row, create new row in same family.
    - Token hash matches a REVOKED session → lock family rows, revoke all
      active family members, raise REFRESH_TOKEN_REUSED.
    - Token not found at all → INVALID_REFRESH_TOKEN.

    The row lock ensures exactly one of two concurrent refreshes succeeds;
    the loser sees revoked_at set and triggers family revocation.
    """
    try:
        token_bytes = bytes.fromhex(refresh_token_hex_val)
    except ValueError:
        raise HTTPException(
            status_code=401,
            detail={
                "error": "INVALID_REFRESH_TOKEN",
                "message": "Invalid or expired refresh token",
            },
        )
    token_hash = sha256_hex(token_bytes)

    # Look up the session row by hash (may be active or already revoked)
    candidate = (
        db.query(AuthSession)
        .filter(AuthSession.refresh_token_hash == token_hash)
        .with_for_update()
        .first()
    )

    if candidate is None:
        raise HTTPException(
            status_code=401,
            detail={
                "error": "INVALID_REFRESH_TOKEN",
                "message": "Invalid or expired refresh token",
            },
        )

    # Re-check state after acquiring the lock
    if candidate.revoked_at is not None:
        # Replay detected — revoke entire family
        db.query(AuthSession).filter(
            AuthSession.family_id == candidate.family_id,
            AuthSession.revoked_at.is_(None),
        ).update({"revoked_at": datetime.now(tz=UTC)})
        raise HTTPException(
            status_code=401,
            detail={
                "error": "REFRESH_TOKEN_REUSED",
                "message": "Refresh token has already been used. All sessions have been revoked.",
            },
        )

    if candidate.expires_at <= datetime.now(tz=UTC):
        raise HTTPException(
            status_code=401,
            detail={
                "error": "INVALID_REFRESH_TOKEN",
                "message": "Invalid or expired refresh token",
            },
        )

    session = candidate

    # Rotate: revoke old session row (preserving hash for future replay detection),
    # then insert a new row in the same family.
    new_bytes = generate_token_bytes(32)
    new_hex = new_bytes.hex()
    new_hash = sha256_hex(new_bytes)
    new_session_id = str(uuid.uuid4())
    new_jti = str(uuid.uuid4())
    new_csrf = generate_token_hex(32)
    new_ip_hash = hashlib.sha256(ip_address.encode()).hexdigest()

    session.revoked_at = datetime.now(tz=UTC)

    # Derive current role from DB (do not trust JWT role claim)
    membership = db.query(Membership).filter(Membership.id == session.membership_id).first()
    role = membership.role if membership and membership.is_active else ""
    org_id = session.org_id if membership and membership.is_active else None
    membership_id = session.membership_id if membership and membership.is_active else None

    new_session = AuthSession(
        id=new_session_id,
        user_id=session.user_id,
        org_id=org_id,
        membership_id=membership_id,
        refresh_token_hash=new_hash,
        family_id=session.family_id,
        ip_address_hash=new_ip_hash,
        user_agent=user_agent or session.user_agent,
        expires_at=datetime.now(tz=UTC) + timedelta(seconds=settings.refresh_token_ttl),
    )
    db.add(new_session)

    access_token = create_access_token(
        user_id=session.user_id,
        session_id=new_session_id,
        org_id=org_id or "",
        membership_id=membership_id or "",
        role=role,
        jti=new_jti,
    )

    return AuthTokens(
        access_token=access_token,
        refresh_token_hex=new_hex,
        csrf_value=new_csrf,
        session_id=new_session_id,
    )


# ── Logout ────────────────────────────────────────────────────────────────────


def logout(db: Session, session_id: str) -> None:
    """Revoke a single session."""
    db.query(AuthSession).filter(
        AuthSession.id == session_id,
        AuthSession.revoked_at.is_(None),
    ).update({"revoked_at": datetime.now(tz=UTC)})


def logout_all(db: Session, user_id: str) -> None:
    """Revoke all active sessions for a user."""
    db.query(AuthSession).filter(
        AuthSession.user_id == user_id,
        AuthSession.revoked_at.is_(None),
    ).update({"revoked_at": datetime.now(tz=UTC)})


# ── Session listing ───────────────────────────────────────────────────────────


def list_sessions(db: Session, user_id: str, current_session_id: str) -> list[dict]:
    """Return all non-revoked, non-expired sessions for the user."""
    sessions = (
        db.query(AuthSession)
        .filter(
            AuthSession.user_id == user_id,
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > datetime.now(tz=UTC),
        )
        .order_by(AuthSession.last_used_at.desc())
        .all()
    )
    return [
        {
            "id": s.id,
            "ip_address_hash": s.ip_address_hash[:8] + "...",
            "user_agent": s.user_agent,
            "last_used_at": s.last_used_at.isoformat(),
            "created_at": s.created_at.isoformat(),
            "current": s.id == current_session_id,
        }
        for s in sessions
    ]


def revoke_session(db: Session, user_id: str, session_id: str) -> None:
    """Revoke a specific session belonging to the user. Raises 404 if not found."""
    session = (
        db.query(AuthSession)
        .filter(AuthSession.id == session_id, AuthSession.user_id == user_id)
        .first()
    )
    if not session:
        raise HTTPException(
            status_code=404,
            detail={"error": "SESSION_NOT_FOUND", "message": "Session not found"},
        )
    session.revoked_at = datetime.now(tz=UTC)


# ── Password reset ────────────────────────────────────────────────────────────


def create_password_reset_token(db: Session, user_id: str) -> str:
    """Generate a password reset token, invalidate prior tokens, return hex token.

    Uses 32 cryptographically random bytes (256-bit entropy). Expiry is
    settings.password_reset_ttl (default 30 minutes). All unused prior reset
    tokens for this user are invalidated on each new request.
    """
    now = datetime.now(tz=UTC)
    # Invalidate all previous unused reset tokens for this user
    db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user_id,
        PasswordResetToken.used_at.is_(None),
        PasswordResetToken.expires_at > now,
    ).update({"used_at": now})

    token_bytes = generate_token_bytes(32)
    token_hex = token_bytes.hex()
    token_hash = sha256_hex(token_bytes)
    reset_token = PasswordResetToken(
        user_id=user_id,
        token_hash=token_hash,
        expires_at=now + timedelta(seconds=settings.password_reset_ttl),
    )
    db.add(reset_token)
    return token_hex


def reset_password(db: Session, token_hex: str, new_password: str) -> None:
    """Reset password using a valid reset token. Raises 401 if invalid.

    Also updates password_changed_at and revokes all active sessions.
    """
    try:
        token_bytes = bytes.fromhex(token_hex)
    except ValueError:
        raise HTTPException(
            status_code=401,
            detail={
                "error": "INVALID_RESET_TOKEN",
                "message": "Invalid or expired password reset link",
            },
        )
    token_hash = sha256_hex(token_bytes)
    reset_token = (
        db.query(PasswordResetToken)
        .filter(
            PasswordResetToken.token_hash == token_hash,
            PasswordResetToken.used_at.is_(None),
            PasswordResetToken.expires_at > datetime.now(tz=UTC),
        )
        .first()
    )
    if not reset_token:
        raise HTTPException(
            status_code=401,
            detail={
                "error": "INVALID_RESET_TOKEN",
                "message": "Invalid or expired password reset link",
            },
        )
    reset_token.used_at = datetime.now(tz=UTC)
    user = db.query(User).filter(User.id == reset_token.user_id).first()
    if user:
        user.hashed_password = hash_password(new_password)
        user.password_changed_at = datetime.now(tz=UTC)
    # Revoke all sessions after password reset (DB-backed auth will reject them)
    db.query(AuthSession).filter(
        AuthSession.user_id == reset_token.user_id,
        AuthSession.revoked_at.is_(None),
    ).update({"revoked_at": datetime.now(tz=UTC)})


def change_password(db: Session, user_id: str, current_password: str, new_password: str) -> None:
    """Change password for authenticated user. Raises 401 if current password wrong."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not verify_password(user.hashed_password, current_password):
        raise HTTPException(
            status_code=401,
            detail={"error": "INVALID_CREDENTIALS", "message": "Current password is incorrect"},
        )
    user.hashed_password = hash_password(new_password)
    user.password_changed_at = datetime.now(tz=UTC)


# ── Org switching ─────────────────────────────────────────────────────────────


def switch_org(
    db: Session,
    user_id: str,
    session_id: str,
    target_org_id: str,
) -> AuthTokens:
    """Switch the active organization for the current session.

    Validates the user has an active membership in the target org,
    updates the session, and issues a new access token.
    Raises 403 if the user is not a member of the target org.
    """
    membership = (
        db.query(Membership)
        .filter(
            Membership.user_id == user_id,
            Membership.org_id == target_org_id,
            Membership.is_active.is_(True),
        )
        .first()
    )
    if not membership:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "NOT_A_MEMBER",
                "message": "You are not a member of that organization",
            },
        )

    session = (
        db.query(AuthSession)
        .filter(AuthSession.id == session_id, AuthSession.revoked_at.is_(None))
        .first()
    )
    if not session:
        raise HTTPException(
            status_code=401,
            detail={"error": "SESSION_NOT_FOUND", "message": "Session not found"},
        )

    session.org_id = target_org_id
    session.membership_id = membership.id

    jti = str(uuid.uuid4())
    new_csrf = generate_token_hex(32)
    access_token = create_access_token(
        user_id=user_id,
        session_id=session_id,
        org_id=target_org_id,
        membership_id=membership.id,
        role=membership.role,
        jti=jti,
    )

    return AuthTokens(
        access_token=access_token,
        refresh_token_hex="",  # Refresh token unchanged on org switch
        csrf_value=new_csrf,
        session_id=session_id,
    )


# ── Email verification helpers ────────────────────────────────────────────────


async def send_verification_email(
    provider: EmailProvider,
    user: User,
    token: str,
) -> None:
    html, text = email_verification(user.full_name, token)
    await provider.send(
        to=user.email,
        subject="Verify your ExpertSeat account",
        html_body=html,
        text_body=text,
        kind="verification",
    )


async def send_password_reset_email(
    provider: EmailProvider,
    user: User,
    reset_token: str,
) -> None:
    html, text = password_reset(user.full_name, reset_token)
    await provider.send(
        to=user.email,
        subject="Reset your ExpertSeat password",
        html_body=html,
        text_body=text,
        kind="password_reset",
    )
