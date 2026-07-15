"""Authentication service.

All auth business logic lives here. Route handlers are thin — they validate
input, call service functions, and set cookies.

Security invariants:
  - Verification tokens: 32 random bytes (256-bit entropy), SHA-256 hash stored.
    Resending invalidates all previous unused tokens for that user.
  - Password reset tokens: 32 random bytes, SHA-256 hash stored, 30-minute TTL.
    A new request invalidates all previous unused reset tokens.
  - Refresh tokens: 32 random bytes, new session row on rotation (old row
    preserved for replay detection).
  - Access tokens: JWT, never returned in JSON — set only in HttpOnly cookie.
  - Refresh replay: family revocation persists even when replay is detected.
    The service raises RefreshReplayDetected (not HTTPException) so the route
    can commit the revocation before returning 401.
  - Absolute session family lifetime: family_expires_at is set at login and
    never extended on rotation.
  - Password change session policy: current session is kept (refresh token
    rotated), all other sessions are revoked.
"""

from __future__ import annotations

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
from app.auth.exceptions import RefreshAccountDisabled, RefreshAccountInvalid, RefreshReplayDetected
from app.auth.tokens import create_access_token
from app.config import settings
from app.email.base import EmailProvider
from app.email.templates import email_verification, password_reset
from app.models.audit import AuditEvent
from app.models.organization import Membership, Organization
from app.models.session import AuthSession
from app.models.user import EmailVerificationToken, PasswordResetToken, User

# ── Audit helper ──────────────────────────────────────────────────────────────


def _write_auth_audit(
    db: Session,
    org_id: str | None,
    actor_id: str | None,
    target_id: str | None,
    event_type: str,
    payload: dict,
    *,
    target_type: str | None = None,
    request_id: str | None = None,
) -> None:
    """Append an auth audit event in the same DB session.

    Sensitive values (passwords, tokens, hashes, IPs) must never appear
    in payload. If this raises, the caller's transaction rolls back too.
    """
    db.add(
        AuditEvent(
            org_id=org_id,
            actor_id=actor_id,
            target_id=target_id,
            target_type=target_type,
            event_type=event_type,
            payload=payload,
            request_id=request_id,
        )
    )


# ── Registration ──────────────────────────────────────────────────────────────


def register_user(
    db: Session,
    email: str,
    password: str,
    full_name: str,
    *,
    request_id: str | None = None,
) -> User:
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
    _write_auth_audit(
        db,
        None,
        user.id,
        user.id,
        "user.registered",
        {},
        target_type="user",
        request_id=request_id,
    )
    return user


def create_email_verification_token(db: Session, user_id: str) -> str:
    """Generate a secure verification token, store its hash, return hex token.

    Uses 32 cryptographically random bytes (256-bit entropy).
    All previous unused verification tokens for this user are invalidated
    (marked used) before creating the new one, so resend always supersedes.
    """
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


def verify_email_token(db: Session, token_hex: str, *, request_id: str | None = None) -> None:
    """Mark user email as verified. Raises 401 if token is invalid or expired."""
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
        _write_auth_audit(
            db,
            None,
            user.id,
            user.id,
            "user.email_verified",
            {},
            target_type="user",
            request_id=request_id,
        )


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
    user_agent: str | None,
    *,
    request_id: str | None = None,
) -> AuthTokens:
    """Authenticate user and create a new auth session.

    Returns AuthTokens. Raises HTTPException on invalid credentials.
    The route handler must write auth.login_failed audit on exception.
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

    if needs_rehash(user.hashed_password):
        user.hashed_password = hash_password(password)

    membership = (
        db.query(Membership)
        .join(Organization, Membership.org_id == Organization.id)
        .filter(
            Membership.user_id == user.id,
            Membership.is_active.is_(True),
            Organization.is_active.is_(True),
        )
        .order_by(Membership.created_at.desc())
        .first()
    )

    if not membership:
        org_id = None
        membership_id = None
        role = ""
    else:
        org_id = membership.org_id
        membership_id = membership.id
        role = membership.role

    tokens = _create_session(db, user.id, org_id, membership_id, role, user_agent)
    _write_auth_audit(
        db,
        org_id,
        user.id,
        user.id,
        "auth.login_succeeded",
        {},
        target_type="user",
        request_id=request_id,
    )
    return tokens


def _create_session(
    db: Session,
    user_id: str,
    org_id: str | None,
    membership_id: str | None,
    role: str,
    user_agent: str | None,
    *,
    family_id: str | None = None,
    family_created_at: datetime | None = None,
    family_expires_at: datetime | None = None,
) -> AuthTokens:
    """Create an auth session row and return tokens.

    When family_id/family_created_at/family_expires_at are provided, this
    session is a successor within an existing family (rotation). The successor
    inherits family_expires_at and its expires_at is capped to never exceed it.
    When omitted, a new family is created (initial login).
    """
    refresh_token_bytes = generate_token_bytes(32)
    refresh_token_hex_val = refresh_token_bytes.hex()
    refresh_token_hash = sha256_hex(refresh_token_bytes)
    new_family_id = family_id or str(uuid.uuid4())
    session_id = str(uuid.uuid4())
    jti = str(uuid.uuid4())

    now = datetime.now(tz=UTC)
    if family_expires_at is None:
        # New family: set absolute family lifetime from now
        family_expires_at = now + timedelta(seconds=settings.refresh_family_ttl)

    # Cap idle expiry at absolute family expiry (never extend family lifetime)
    expires_at = min(now + timedelta(seconds=settings.refresh_token_ttl), family_expires_at)

    session = AuthSession(
        id=session_id,
        user_id=user_id,
        org_id=org_id,
        membership_id=membership_id,
        refresh_token_hash=refresh_token_hash,
        family_id=new_family_id,
        user_agent_summary=(user_agent or "")[:200] or None,
        family_created_at=family_created_at,
        family_expires_at=family_expires_at,
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
    user_agent: str | None,
    *,
    request_id: str | None = None,
) -> AuthTokens:
    """Rotate refresh token and issue new access token.

    Transaction boundary contract:
      - On replay detected: marks family revoked, raises RefreshReplayDetected.
        The caller MUST db.commit() before returning 401.
      - On account invalid: raises RefreshAccountInvalid (no commit needed).
      - On success: caller commits after receiving AuthTokens.

    Account validation policy (after acquiring lock):
      - User must exist, be active, and be email-verified.
      - If workspace context carries an invalid/inactive membership or org,
        the successor session is issued with no workspace context (Policy B:
        rotate into no-workspace session, not family revocation). The user
        remains authenticated but loses workspace access until they switch org.

    Absolute family lifetime:
      - family_expires_at is inherited from the predecessor and never extended.
      - If family_expires_at <= now, the token is rejected as expired.
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

    # Acquire row lock before reading state (prevents TOCTOU race)
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

    # Replay detection: token already used → revoke family, raise domain exception
    if candidate.revoked_at is not None:
        now = datetime.now(tz=UTC)
        db.query(AuthSession).filter(
            AuthSession.family_id == candidate.family_id,
            AuthSession.revoked_at.is_(None),
        ).update({"revoked_at": now})
        _write_auth_audit(
            db,
            candidate.org_id,
            candidate.user_id,
            candidate.user_id,
            "auth.refresh_reuse_detected",
            {"family_id": candidate.family_id},
            target_type="session",
            request_id=request_id,
        )
        # Domain exception: caller commits revocation, then returns 401
        raise RefreshReplayDetected(candidate.family_id)

    now = datetime.now(tz=UTC)

    # Check absolute family lifetime
    if candidate.family_expires_at <= now:
        raise HTTPException(
            status_code=401,
            detail={
                "error": "SESSION_EXPIRED",
                "message": "Session family has expired. Please sign in again.",
            },
        )

    # Check per-token idle expiration
    if candidate.expires_at <= now:
        raise HTTPException(
            status_code=401,
            detail={
                "error": "INVALID_REFRESH_TOKEN",
                "message": "Invalid or expired refresh token",
            },
        )

    # Validate user account state
    user = db.query(User).filter(User.id == candidate.user_id).first()
    if not user:
        raise RefreshAccountInvalid("ACCOUNT_INVALID", "Account not found")
    if not user.is_active:
        # Revoke entire family, then raise so route commits revocation before 401
        db.query(AuthSession).filter(
            AuthSession.family_id == candidate.family_id,
            AuthSession.revoked_at.is_(None),
        ).update({"revoked_at": now})
        _write_auth_audit(
            db,
            candidate.org_id,
            candidate.user_id,
            candidate.user_id,
            "auth.session_revoked_account_disabled",
            {"family_id": candidate.family_id},
            target_type="session",
            request_id=request_id,
        )
        raise RefreshAccountDisabled(candidate.user_id)
    if not user.email_verified:
        raise RefreshAccountInvalid("ACCOUNT_UNVERIFIED", "Email verification required")

    # Validate workspace context (Policy B: strip invalid context, do not revoke)
    org_id: str | None = candidate.org_id
    membership_id: str | None = candidate.membership_id
    role = ""

    if org_id and membership_id:
        membership = (
            db.query(Membership)
            .filter(
                Membership.id == membership_id,
                Membership.user_id == candidate.user_id,
                Membership.org_id == org_id,
                Membership.is_active.is_(True),
            )
            .first()
        )
        org = (
            (
                db.query(Organization)
                .filter(Organization.id == org_id, Organization.is_active.is_(True))
                .first()
            )
            if membership
            else None
        )

        if membership and org:
            role = membership.role
        else:
            # Workspace context is invalid — strip to no-workspace session
            org_id = None
            membership_id = None

    # Revoke predecessor row (keep hash for replay detection)
    candidate.revoked_at = now

    # Create successor row in the same family
    new_bytes = generate_token_bytes(32)
    new_hex = new_bytes.hex()
    new_hash = sha256_hex(new_bytes)
    new_session_id = str(uuid.uuid4())
    new_jti = str(uuid.uuid4())
    new_csrf = generate_token_hex(32)

    # Cap idle expiry at absolute family expiry (never extend family lifetime)
    successor_expires_at = min(
        now + timedelta(seconds=settings.refresh_token_ttl),
        candidate.family_expires_at,
    )

    new_session = AuthSession(
        id=new_session_id,
        user_id=candidate.user_id,
        org_id=org_id,
        membership_id=membership_id,
        refresh_token_hash=new_hash,
        family_id=candidate.family_id,
        user_agent_summary=(user_agent or candidate.user_agent_summary or "")[:200] or None,
        family_created_at=candidate.family_created_at,
        family_expires_at=candidate.family_expires_at,  # never extended
        expires_at=successor_expires_at,
    )
    db.add(new_session)

    _write_auth_audit(
        db,
        org_id,
        candidate.user_id,
        new_session_id,
        "auth.refresh_rotated",
        {},
        target_type="session",
        request_id=request_id,
    )

    access_token = create_access_token(
        user_id=candidate.user_id,
        session_id=new_session_id,
        org_id=org_id,
        membership_id=membership_id,
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


def logout(
    db: Session,
    session_id: str,
    user_id: str,
    org_id: str | None,
    *,
    request_id: str | None = None,
) -> None:
    """Revoke a single session and write audit event."""
    db.query(AuthSession).filter(
        AuthSession.id == session_id,
        AuthSession.revoked_at.is_(None),
    ).update({"revoked_at": datetime.now(tz=UTC)})
    _write_auth_audit(
        db,
        org_id,
        user_id,
        session_id,
        "auth.logout",
        {},
        target_type="session",
        request_id=request_id,
    )


def logout_all(
    db: Session,
    user_id: str,
    org_id: str | None,
    *,
    request_id: str | None = None,
) -> None:
    """Revoke all active sessions for a user and write audit event."""
    db.query(AuthSession).filter(
        AuthSession.user_id == user_id,
        AuthSession.revoked_at.is_(None),
    ).update({"revoked_at": datetime.now(tz=UTC)})
    _write_auth_audit(
        db,
        org_id,
        user_id,
        user_id,
        "auth.logout_all",
        {},
        target_type="user",
        request_id=request_id,
    )


# ── Session listing ───────────────────────────────────────────────────────────


def list_sessions(db: Session, user_id: str, current_session_id: str) -> list[dict]:
    """Return all non-revoked, non-expired sessions for the user.

    A session is excluded when either:
      - revoked_at IS NOT NULL (explicitly revoked)
      - expires_at <= now (idle TTL exceeded)
      - family_expires_at <= now (absolute family lifetime exceeded)
    """
    now = datetime.now(tz=UTC)
    sessions = (
        db.query(AuthSession)
        .filter(
            AuthSession.user_id == user_id,
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > now,
            AuthSession.family_expires_at > now,
        )
        .order_by(AuthSession.last_used_at.desc())
        .all()
    )
    return [
        {
            "id": s.id,
            "user_agent_summary": s.user_agent_summary,
            "last_used_at": s.last_used_at.isoformat(),
            "created_at": s.created_at.isoformat(),
            "current": s.id == current_session_id,
        }
        for s in sessions
    ]


def revoke_session(
    db: Session,
    user_id: str,
    session_id: str,
    org_id: str | None,
    *,
    request_id: str | None = None,
) -> None:
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
    _write_auth_audit(
        db,
        org_id,
        user_id,
        session_id,
        "auth.session_revoked",
        {},
        target_type="session",
        request_id=request_id,
    )


# ── Password reset ────────────────────────────────────────────────────────────


def create_password_reset_token(db: Session, user_id: str) -> str:
    """Generate a password reset token, invalidate prior tokens, return hex token."""
    now = datetime.now(tz=UTC)
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


def reset_password(
    db: Session,
    token_hex: str,
    new_password: str,
    *,
    request_id: str | None = None,
) -> None:
    """Reset password using a valid reset token.

    Revokes all active sessions and updates password_changed_at.
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
        db.query(AuthSession).filter(
            AuthSession.user_id == user.id,
            AuthSession.revoked_at.is_(None),
        ).update({"revoked_at": datetime.now(tz=UTC)})
        _write_auth_audit(
            db,
            None,
            user.id,
            user.id,
            "auth.password_reset_completed",
            {},
            target_type="user",
            request_id=request_id,
        )


def change_password(
    db: Session,
    user_id: str,
    current_session_id: str,
    current_password: str,
    new_password: str,
    current_org_id: str | None,
    current_user_agent: str | None,
    *,
    request_id: str | None = None,
) -> AuthTokens:
    """Change password for authenticated user.

    Password-change session policy:
      - Current session is kept active (refresh token rotated).
      - All other session families are revoked immediately.
      - password_changed_at is updated.
      - auth.password_changed audit event is written.

    Raises 401 if current_password is wrong.
    Returns new AuthTokens for the current session (caller must set cookies).
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not verify_password(user.hashed_password, current_password):
        raise HTTPException(
            status_code=401,
            detail={"error": "INVALID_CREDENTIALS", "message": "Current password is incorrect"},
        )
    user.hashed_password = hash_password(new_password)
    user.password_changed_at = datetime.now(tz=UTC)

    # Revoke all sessions EXCEPT the current session's family
    current_session = (
        db.query(AuthSession)
        .filter(AuthSession.id == current_session_id, AuthSession.revoked_at.is_(None))
        .first()
    )
    if current_session:
        current_family_id = current_session.family_id
        # Revoke all OTHER families
        db.query(AuthSession).filter(
            AuthSession.user_id == user_id,
            AuthSession.family_id != current_family_id,
            AuthSession.revoked_at.is_(None),
        ).update({"revoked_at": datetime.now(tz=UTC)})
        # Rotate current session's refresh token
        current_session.revoked_at = datetime.now(tz=UTC)
        membership_id = current_session.membership_id
        org_id = current_session.org_id

        # Derive role from DB
        role = ""
        if membership_id:
            membership = (
                db.query(Membership)
                .filter(Membership.id == membership_id, Membership.is_active.is_(True))
                .first()
            )
            if membership:
                role = membership.role

        new_bytes = generate_token_bytes(32)
        new_hex = new_bytes.hex()
        new_hash = sha256_hex(new_bytes)
        new_session_id = str(uuid.uuid4())
        new_jti = str(uuid.uuid4())
        new_csrf = generate_token_hex(32)
        now = datetime.now(tz=UTC)

        # Cap idle expiry at absolute family expiry (never extend family lifetime)
        successor_expires_at = min(
            now + timedelta(seconds=settings.refresh_token_ttl),
            current_session.family_expires_at,
        )

        new_session = AuthSession(
            id=new_session_id,
            user_id=user_id,
            org_id=org_id,
            membership_id=membership_id,
            refresh_token_hash=new_hash,
            family_id=current_family_id,
            user_agent_summary=(current_user_agent or current_session.user_agent_summary or "")[
                :200
            ]
            or None,
            family_created_at=current_session.family_created_at,
            family_expires_at=current_session.family_expires_at,
            expires_at=successor_expires_at,
        )
        db.add(new_session)

        access_token = create_access_token(
            user_id=user_id,
            session_id=new_session_id,
            org_id=org_id,
            membership_id=membership_id,
            role=role,
            jti=new_jti,
        )
        _write_auth_audit(
            db,
            current_org_id,
            user_id,
            user_id,
            "auth.password_changed",
            {},
            target_type="user",
            request_id=request_id,
        )
        return AuthTokens(
            access_token=access_token,
            refresh_token_hex=new_hex,
            csrf_value=new_csrf,
            session_id=new_session_id,
        )
    else:
        # Session not found — revoke all and issue new login required
        db.query(AuthSession).filter(
            AuthSession.user_id == user_id,
            AuthSession.revoked_at.is_(None),
        ).update({"revoked_at": datetime.now(tz=UTC)})
        _write_auth_audit(
            db,
            current_org_id,
            user_id,
            user_id,
            "auth.password_changed",
            {},
            target_type="user",
            request_id=request_id,
        )
        raise HTTPException(
            status_code=401,
            detail={
                "error": "SESSION_NOT_FOUND",
                "message": "Session not found. Please sign in again.",
            },
        )


# ── Org switching ─────────────────────────────────────────────────────────────


def switch_org(
    db: Session,
    user_id: str,
    session_id: str,
    target_org_id: str,
    *,
    request_id: str | None = None,
) -> AuthTokens:
    """Switch the active organization for the current session."""
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
    _write_auth_audit(
        db,
        target_org_id,
        user_id,
        target_org_id,
        "workspace.switched",
        {},
        target_type="organization",
        request_id=request_id,
    )

    return AuthTokens(
        access_token=access_token,
        refresh_token_hex="",
        csrf_value=new_csrf,
        session_id=session_id,
    )


# ── Account enable / disable ──────────────────────────────────────────────────


def disable_user_account(
    db: Session,
    target_user_id: str,
    actor_id: str,
    org_id: str | None,
    *,
    request_id: str | None = None,
) -> None:
    """Disable a user account and immediately revoke all their active sessions.

    Session revocation is always paired with account disable so no caller
    can forget it. Re-enabling (enable_user_account) does NOT restore sessions —
    the user must sign in again.

    Raises 404 if user not found, 409 if already disabled.
    """
    user = db.query(User).filter(User.id == target_user_id).first()
    if not user:
        raise HTTPException(
            status_code=404,
            detail={"error": "USER_NOT_FOUND", "message": "User not found"},
        )
    if not user.is_active:
        raise HTTPException(
            status_code=409,
            detail={"error": "ALREADY_DISABLED", "message": "Account is already disabled"},
        )
    user.is_active = False
    # Revoke all active sessions immediately
    db.query(AuthSession).filter(
        AuthSession.user_id == target_user_id,
        AuthSession.revoked_at.is_(None),
    ).update({"revoked_at": datetime.now(tz=UTC)})
    _write_auth_audit(
        db,
        org_id,
        actor_id,
        target_user_id,
        "auth.account_disabled",
        {},
        target_type="user",
        request_id=request_id,
    )


def enable_user_account(
    db: Session,
    target_user_id: str,
    actor_id: str,
    org_id: str | None,
    *,
    request_id: str | None = None,
) -> None:
    """Enable a previously disabled user account.

    Does NOT restore revoked sessions — the user must sign in again.
    Raises 404 if user not found, 409 if already active.
    """
    user = db.query(User).filter(User.id == target_user_id).first()
    if not user:
        raise HTTPException(
            status_code=404,
            detail={"error": "USER_NOT_FOUND", "message": "User not found"},
        )
    if user.is_active:
        raise HTTPException(
            status_code=409,
            detail={"error": "ALREADY_ACTIVE", "message": "Account is already active"},
        )
    user.is_active = True
    _write_auth_audit(
        db,
        org_id,
        actor_id,
        target_user_id,
        "auth.account_enabled",
        {},
        target_type="user",
        request_id=request_id,
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
