"""Workspace (organization) service.

Business logic for: org creation, member management, invitations,
settings, and audit log.

All functions operate on the org_id derived from the JWT workspace context
(never from caller-supplied parameters as the authorization context).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.auth.crypto import generate_token_bytes, sha256_hex
from app.email.base import EmailProvider
from app.email.templates import workspace_invitation
from app.models.audit import AuditEvent
from app.models.organization import Membership, Organization, OrganizationInvitation
from app.models.session import AuthSession
from app.models.user import User

if TYPE_CHECKING:
    from app.services.auth import AuthTokens

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,46}[a-z0-9]$")
_INVITATION_TTL_DAYS = 7


# ── Slug utilities ────────────────────────────────────────────────────────────


def _slugify(name: str) -> str:
    """Convert an org name to a URL-safe slug."""
    slug = name.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug[:48] if len(slug) > 48 else slug


def _ensure_unique_slug(db: Session, base_slug: str) -> str:
    """Append a numeric suffix until the slug is unique."""
    slug = base_slug
    counter = 2
    while db.query(Organization).filter(Organization.slug == slug).first():
        slug = f"{base_slug[:45]}-{counter}"
        counter += 1
    return slug


# ── Organization creation ──────────────────────────────────────────────────────


def create_organization(
    db: Session,
    name: str,
    creator_user_id: str,
    *,
    request_id: str | None = None,
) -> Organization:
    """Create a new organization and make the creator an admin."""
    base_slug = _slugify(name)
    if not base_slug:
        raise HTTPException(
            status_code=400,
            detail={"error": "INVALID_NAME", "message": "Organization name is invalid"},
        )
    slug = _ensure_unique_slug(db, base_slug)
    org = Organization(name=name, slug=slug)
    db.add(org)
    db.flush()

    membership = Membership(
        user_id=creator_user_id,
        org_id=org.id,
        role="admin",
        is_active=True,
    )
    db.add(membership)
    db.flush()

    _write_audit(
        db,
        org.id,
        creator_user_id,
        None,
        "org.created",
        {"name": name, "slug": slug},
        target_type="organization",
        request_id=request_id,
    )
    return org


def update_organization(
    db: Session,
    org_id: str,
    actor_id: str,
    name: str | None,
    slug: str | None,
    *,
    request_id: str | None = None,
) -> Organization:
    """Update organization name and/or slug. Admin only."""
    org = _require_org(db, org_id)
    if name is not None:
        org.name = name
    if slug is not None:
        if not _SLUG_RE.match(slug):
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "INVALID_SLUG",
                    "message": "Slug must be 3-48 lowercase alphanumeric characters or hyphens",
                },
            )
        existing = (
            db.query(Organization)
            .filter(Organization.slug == slug, Organization.id != org_id)
            .first()
        )
        if existing:
            raise HTTPException(
                status_code=409,
                detail={"error": "SLUG_ALREADY_EXISTS", "message": "That slug is already taken"},
            )
        org.slug = slug
    _write_audit(
        db,
        org_id,
        actor_id,
        org_id,
        "org.settings_updated",
        {"name": name, "slug": slug},
        target_type="organization",
        request_id=request_id,
    )
    return org


def get_organization(db: Session, org_id: str) -> Organization:
    return _require_org(db, org_id)


def list_user_organizations(db: Session, user_id: str) -> list[Organization]:
    """Return all organizations the user is an active member of."""
    memberships = (
        db.query(Membership)
        .filter(Membership.user_id == user_id, Membership.is_active.is_(True))
        .all()
    )
    org_ids = [m.org_id for m in memberships]
    if not org_ids:
        return []
    return db.query(Organization).filter(Organization.id.in_(org_ids)).all()


# ── Member management ──────────────────────────────────────────────────────────


def list_members(db: Session, org_id: str) -> list[dict]:
    """Return all active memberships with user info."""
    rows = (
        db.query(Membership, User)
        .join(User, Membership.user_id == User.id)
        .filter(Membership.org_id == org_id, Membership.is_active.is_(True))
        .order_by(Membership.created_at.asc())
        .all()
    )
    return [
        {
            "membership_id": m.id,
            "user_id": u.id,
            "email": u.email,
            "full_name": u.full_name,
            "role": m.role,
            "is_active": m.is_active,
            "joined_at": m.created_at.isoformat(),
        }
        for m, u in rows
    ]


def get_member(db: Session, org_id: str, user_id: str) -> dict:
    result = (
        db.query(Membership, User)
        .join(User, Membership.user_id == User.id)
        .filter(Membership.org_id == org_id, Membership.user_id == user_id)
        .first()
    )
    if not result:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "MEMBER_NOT_FOUND",
                "message": "Member not found in this organization",
            },
        )
    m, u = result
    return {
        "membership_id": m.id,
        "user_id": u.id,
        "email": u.email,
        "full_name": u.full_name,
        "role": m.role,
        "is_active": m.is_active,
        "joined_at": m.created_at.isoformat(),
    }


def update_member_role(
    db: Session,
    org_id: str,
    target_user_id: str,
    new_role: str,
    actor_id: str,
    *,
    request_id: str | None = None,
) -> dict:
    """Change a member's role. Raises 409 if demoting the last admin."""
    if new_role not in ("admin", "recruiter", "reviewer"):
        raise HTTPException(
            status_code=400,
            detail={
                "error": "INVALID_ROLE",
                "message": "Role must be admin, recruiter, or reviewer",
            },
        )
    membership = _require_membership(db, org_id, target_user_id)
    old_role = membership.role

    if old_role == "admin" and new_role != "admin":
        _check_not_last_admin(db, org_id, target_user_id, actor_id, request_id=request_id)

    membership.role = new_role
    _write_audit(
        db,
        org_id,
        actor_id,
        target_user_id,
        "member.role_changed",
        {"old_role": old_role, "new_role": new_role},
        target_type="user",
        request_id=request_id,
    )
    return get_member(db, org_id, target_user_id)


def set_member_active(
    db: Session,
    org_id: str,
    target_user_id: str,
    is_active: bool,
    actor_id: str,
    *,
    request_id: str | None = None,
) -> dict:
    """Enable or disable a member. Raises 409 if disabling the last admin."""
    membership = _require_membership(db, org_id, target_user_id)

    if not is_active and membership.role == "admin":
        _check_not_last_admin(db, org_id, target_user_id, actor_id, request_id=request_id)

    membership.is_active = is_active
    action = "member.enabled" if is_active else "member.disabled"
    _write_audit(
        db,
        org_id,
        actor_id,
        target_user_id,
        action,
        {},
        target_type="user",
        request_id=request_id,
    )
    return get_member(db, org_id, target_user_id)


def remove_member(
    db: Session,
    org_id: str,
    target_user_id: str,
    actor_id: str,
    *,
    request_id: str | None = None,
) -> None:
    """Remove a member from the org. Raises 409 if removing the last admin."""
    membership = _require_membership(db, org_id, target_user_id)
    if membership.role == "admin":
        _check_not_last_admin(db, org_id, target_user_id, actor_id, request_id=request_id)
    db.delete(membership)
    # Revoke their sessions in this org
    db.query(AuthSession).filter(
        AuthSession.user_id == target_user_id,
        AuthSession.org_id == org_id,
        AuthSession.revoked_at.is_(None),
    ).update({"revoked_at": datetime.now(tz=UTC)})
    _write_audit(
        db,
        org_id,
        actor_id,
        target_user_id,
        "member.removed",
        {},
        target_type="user",
        request_id=request_id,
    )


def _check_not_last_admin(
    db: Session,
    org_id: str,
    target_user_id: str,
    actor_id: str | None = None,
    *,
    request_id: str | None = None,
) -> None:
    """Raise 409 if the target is the only active admin in the org.

    Uses SELECT FOR UPDATE to lock all active admin memberships for this org,
    preventing concurrent demotions or removals from racing and leaving zero admins.
    The lock is held until the caller's transaction commits or rolls back.

    If blocking, writes a last_admin.action_blocked audit event in an independent
    transaction (so it persists even though the caller's transaction rolls back).
    """
    admin_memberships = (
        db.query(Membership)
        .filter(
            Membership.org_id == org_id,
            Membership.role == "admin",
            Membership.is_active.is_(True),
        )
        .with_for_update()
        .all()
    )
    admin_count = len(admin_memberships)
    target_is_admin = any(m.user_id == target_user_id for m in admin_memberships)
    if admin_count == 1 and target_is_admin:
        _write_audit_independent(
            "last_admin.action_blocked",
            org_id,
            actor_id,
            target_user_id,
            {},
            target_type="user",
            request_id=request_id,
        )
        raise HTTPException(
            status_code=409,
            detail={
                "error": "LAST_ADMIN_PROTECTED",
                "message": "Cannot remove or demote the last admin of an organization",
            },
        )


# ── Invitations ────────────────────────────────────────────────────────────────


def create_invitation(
    db: Session,
    org_id: str,
    email: str,
    role: str,
    invited_by: str,
    *,
    request_id: str | None = None,
) -> OrganizationInvitation:
    """Create an invitation.

    Raises:
      409 ALREADY_A_MEMBER           — email belongs to an active member
      409 INVITATION_ALREADY_PENDING — a valid pending invitation exists
      400 INVALID_ROLE               — role not in allowed set
    """
    if role not in ("admin", "recruiter", "reviewer"):
        raise HTTPException(
            status_code=400,
            detail={
                "error": "INVALID_ROLE",
                "message": "Role must be admin, recruiter, or reviewer",
            },
        )

    # Check if the email belongs to an existing active member
    existing_member = (
        db.query(Membership, User)
        .join(User, Membership.user_id == User.id)
        .filter(
            Membership.org_id == org_id,
            Membership.is_active.is_(True),
            User.email == email.lower(),
        )
        .first()
    )
    if existing_member:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "ALREADY_A_MEMBER",
                "message": "This email address is already an active member of the organization",
            },
        )

    # Check for existing active invitation
    existing = (
        db.query(OrganizationInvitation)
        .filter(
            OrganizationInvitation.org_id == org_id,
            OrganizationInvitation.email == email.lower(),
            OrganizationInvitation.accepted_at.is_(None),
            OrganizationInvitation.revoked_at.is_(None),
            OrganizationInvitation.expires_at > datetime.now(tz=UTC),
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "INVITATION_ALREADY_PENDING",
                "message": "A pending invitation already exists for this email",
            },
        )
    token_bytes = generate_token_bytes(32)
    token_hex = token_bytes.hex()
    token_hash = sha256_hex(token_bytes)
    invitation = OrganizationInvitation(
        org_id=org_id,
        email=email.lower(),
        role=role,
        invited_by=invited_by,
        token_hash=token_hash,
        expires_at=datetime.now(tz=UTC) + timedelta(days=_INVITATION_TTL_DAYS),
    )
    db.add(invitation)
    db.flush()
    _write_audit(
        db,
        org_id,
        invited_by,
        invitation.id,
        "invitation.created",
        {"email": email, "role": role},
        target_type="invitation",
        request_id=request_id,
    )
    # Return the invitation with the plaintext token set as a transient attribute
    invitation._plaintext_token = token_hex  # type: ignore[attr-defined]
    return invitation


def list_invitations(db: Session, org_id: str) -> list[dict]:
    rows = (
        db.query(OrganizationInvitation)
        .filter(
            OrganizationInvitation.org_id == org_id,
            OrganizationInvitation.accepted_at.is_(None),
            OrganizationInvitation.revoked_at.is_(None),
            OrganizationInvitation.expires_at > datetime.now(tz=UTC),
        )
        .order_by(OrganizationInvitation.created_at.desc())
        .all()
    )
    return [
        {
            "id": inv.id,
            "email": inv.email,
            "role": inv.role,
            "expires_at": inv.expires_at.isoformat(),
            "created_at": inv.created_at.isoformat(),
        }
        for inv in rows
    ]


def revoke_invitation(
    db: Session,
    org_id: str,
    invitation_id: str,
    actor_id: str,
    *,
    request_id: str | None = None,
) -> None:
    inv = (
        db.query(OrganizationInvitation)
        .filter(
            OrganizationInvitation.id == invitation_id,
            OrganizationInvitation.org_id == org_id,
            OrganizationInvitation.revoked_at.is_(None),
        )
        .first()
    )
    if not inv:
        raise HTTPException(
            status_code=404,
            detail={"error": "INVITATION_NOT_FOUND", "message": "Invitation not found"},
        )
    inv.revoked_at = datetime.now(tz=UTC)
    _write_audit(
        db,
        org_id,
        actor_id,
        invitation_id,
        "invitation.revoked",
        {"email": inv.email},
        target_type="invitation",
        request_id=request_id,
    )


def accept_invitation(
    db: Session,
    token_hex: str,
    user_id: str,
    *,
    request_id: str | None = None,
) -> tuple[Organization, Membership]:
    """Accept an invitation. User must already have a verified account."""
    token_bytes = bytes.fromhex(token_hex)
    token_hash = sha256_hex(token_bytes)
    inv = (
        db.query(OrganizationInvitation)
        .filter(
            OrganizationInvitation.token_hash == token_hash,
            OrganizationInvitation.accepted_at.is_(None),
            OrganizationInvitation.revoked_at.is_(None),
            OrganizationInvitation.expires_at > datetime.now(tz=UTC),
        )
        .first()
    )
    if not inv:
        raise HTTPException(
            status_code=401,
            detail={"error": "INVALID_INVITATION", "message": "Invalid or expired invitation"},
        )
    # Verify the accepting user's email matches the invitation
    user = db.query(User).filter(User.id == user_id).first()
    if not user or user.email != inv.email:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "EMAIL_MISMATCH",
                "message": "This invitation was sent to a different email address",
            },
        )
    # Check if already a member
    existing_membership = (
        db.query(Membership)
        .filter(Membership.user_id == user_id, Membership.org_id == inv.org_id)
        .first()
    )
    if existing_membership:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "ALREADY_A_MEMBER",
                "message": "You are already a member of this organization",
            },
        )
    inv.accepted_at = datetime.now(tz=UTC)
    membership = Membership(
        user_id=user_id,
        org_id=inv.org_id,
        role=inv.role,
        is_active=True,
    )
    db.add(membership)
    db.flush()
    org = _require_org(db, inv.org_id)
    _write_audit(
        db,
        inv.org_id,
        user_id,
        inv.id,
        "invitation.accepted",
        {"role": inv.role},
        target_type="invitation",
        request_id=request_id,
    )
    return org, membership


def update_invitation_delivery(
    db: Session,
    invitation_id: str,
    status: str,
    failure_code: str | None = None,
) -> None:
    """Record the outcome of an email delivery attempt."""
    now = datetime.now(tz=UTC)
    db.query(OrganizationInvitation).filter(OrganizationInvitation.id == invitation_id).update(
        {
            "delivery_status": status,
            "delivery_attempted_at": now,
            "delivery_failure_code": failure_code,
        }
    )


def resend_invitation(
    db: Session,
    org_id: str,
    invitation_id: str,
    actor_id: str,
    *,
    request_id: str | None = None,
) -> OrganizationInvitation:
    """Resend an invitation, rotating the token. Raises 404 if not found."""
    inv = (
        db.query(OrganizationInvitation)
        .filter(
            OrganizationInvitation.id == invitation_id,
            OrganizationInvitation.org_id == org_id,
            OrganizationInvitation.accepted_at.is_(None),
            OrganizationInvitation.revoked_at.is_(None),
            OrganizationInvitation.expires_at > datetime.now(tz=UTC),
        )
        .with_for_update()
        .first()
    )
    if not inv:
        raise HTTPException(
            status_code=404,
            detail={"error": "INVITATION_NOT_FOUND", "message": "Active invitation not found"},
        )
    # Rotate the token (old token is now invalid)
    token_bytes = generate_token_bytes(32)
    token_hex = token_bytes.hex()
    token_hash = sha256_hex(token_bytes)
    inv.token_hash = token_hash
    inv.delivery_status = "pending"
    inv.delivery_attempted_at = None
    inv.delivery_failure_code = None
    inv._plaintext_token = token_hex  # type: ignore[attr-defined]
    _write_audit(
        db,
        org_id,
        actor_id,
        invitation_id,
        "invitation.resent",
        {"email": inv.email},
        target_type="invitation",
        request_id=request_id,
    )
    return inv


def preview_invitation(db: Session, token_hex: str) -> dict:
    """Return safe preview of an invitation for unregistered users.
    Never reveals the full email — masks it.
    """
    try:
        token_bytes = bytes.fromhex(token_hex)
    except ValueError:
        raise HTTPException(
            status_code=401,
            detail={"error": "INVALID_INVITATION", "message": "Invalid or expired invitation"},
        )
    token_hash = sha256_hex(token_bytes)
    inv = (
        db.query(OrganizationInvitation)
        .filter(
            OrganizationInvitation.token_hash == token_hash,
            OrganizationInvitation.accepted_at.is_(None),
            OrganizationInvitation.revoked_at.is_(None),
            OrganizationInvitation.expires_at > datetime.now(tz=UTC),
        )
        .first()
    )
    if not inv:
        raise HTTPException(
            status_code=401,
            detail={"error": "INVALID_INVITATION", "message": "Invalid or expired invitation"},
        )
    org = db.query(Organization).filter(Organization.id == inv.org_id).first()
    org_name = org.name if org else "Unknown"
    # Mask the email: show first char + *** + @domain
    email = inv.email
    local, _, domain = email.partition("@")
    masked = local[0] + "***" if len(local) > 1 else "***"
    return {
        "organization_name": org_name,
        "role": inv.role,
        "invited_email_masked": masked + "@" + domain,
        "expires_at": inv.expires_at.isoformat(),
    }


def accept_invitation_new_user(
    db: Session,
    token_hex: str,
    full_name: str,
    password: str,
    *,
    user_agent: str | None = None,
    request_id: str | None = None,
) -> tuple[Organization, Membership, AuthTokens]:
    """Create a new user account via an invitation token and join the org.

    Token possession serves as email-ownership verification — the new account
    is created with email_verified=True immediately.

    Uses SELECT FOR UPDATE on the invitation row to prevent concurrent duplicate
    user creation attempts from both succeeding.

    Returns (org, membership, auth_tokens) so the route can set cookies.
    """
    from app.auth.crypto import hash_password
    from app.services.auth import _create_session, _write_auth_audit

    try:
        token_bytes = bytes.fromhex(token_hex)
    except ValueError:
        raise HTTPException(
            status_code=401,
            detail={"error": "INVALID_INVITATION", "message": "Invalid or expired invitation"},
        )
    token_hash = sha256_hex(token_bytes)

    # Lock the invitation row to prevent concurrent acceptance
    inv = (
        db.query(OrganizationInvitation)
        .filter(
            OrganizationInvitation.token_hash == token_hash,
            OrganizationInvitation.accepted_at.is_(None),
            OrganizationInvitation.revoked_at.is_(None),
            OrganizationInvitation.expires_at > datetime.now(tz=UTC),
        )
        .with_for_update()
        .first()
    )
    if not inv:
        raise HTTPException(
            status_code=401,
            detail={"error": "INVALID_INVITATION", "message": "Invalid or expired invitation"},
        )

    # Check no existing user with that email (concurrent race protection)
    existing = db.query(User).filter(User.email == inv.email).first()
    if existing:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "EMAIL_ALREADY_EXISTS",
                "message": "An account with this email already exists",
            },
        )

    # Create user — token possession = email verified
    user = User(
        email=inv.email,
        hashed_password=hash_password(password),
        full_name=full_name,
        email_verified=True,
        is_active=True,
    )
    db.add(user)
    db.flush()

    # Mark invitation accepted
    inv.accepted_at = datetime.now(tz=UTC)

    # Create membership
    membership = Membership(
        user_id=user.id,
        org_id=inv.org_id,
        role=inv.role,
        is_active=True,
    )
    db.add(membership)
    db.flush()

    org = _require_org(db, inv.org_id)

    # Write audit events
    _write_audit(
        db,
        inv.org_id,
        user.id,
        user.id,
        "user.registered",
        {},
        target_type="user",
        request_id=request_id,
    )
    _write_audit(
        db,
        inv.org_id,
        user.id,
        inv.id,
        "invitation.accepted",
        {"role": inv.role},
        target_type="invitation",
        request_id=request_id,
    )

    # Create session (auto-login)
    tokens = _create_session(db, user.id, inv.org_id, membership.id, inv.role, user_agent)
    _write_auth_audit(
        db,
        inv.org_id,
        user.id,
        user.id,
        "auth.login_succeeded",
        {},
        target_type="user",
        request_id=request_id,
    )

    return org, membership, tokens


# ── Audit log ──────────────────────────────────────────────────────────────────


def get_audit_log(db: Session, org_id: str, limit: int = 50, offset: int = 0) -> list[dict]:
    rows = (
        db.query(AuditEvent)
        .filter(AuditEvent.org_id == org_id)
        .order_by(AuditEvent.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [
        {
            "id": row.id,
            "actor_id": row.actor_id,
            "target_id": row.target_id,
            "target_type": row.target_type,
            "event_type": row.event_type,
            "payload": row.payload,
            "request_id": row.request_id,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]


# ── Private helpers ────────────────────────────────────────────────────────────


def _require_org(db: Session, org_id: str) -> Organization:
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if not org:
        raise HTTPException(
            status_code=404,
            detail={"error": "ORGANIZATION_NOT_FOUND", "message": "Organization not found"},
        )
    return org


def _require_membership(db: Session, org_id: str, user_id: str) -> Membership:
    membership = (
        db.query(Membership)
        .filter(Membership.org_id == org_id, Membership.user_id == user_id)
        .first()
    )
    if not membership:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "MEMBER_NOT_FOUND",
                "message": "Member not found in this organization",
            },
        )
    return membership


def _write_audit(
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
    """Append an audit event in the same transaction as the business mutation.

    Audit events are not optional — they commit atomically with the mutation that
    caused them. If the audit INSERT fails, the business mutation rolls back too.
    This is the same-transaction audit model: audit failure = business failure.

    Sensitive values (passwords, tokens) must never appear in payload.
    """
    event = AuditEvent(
        org_id=org_id,
        actor_id=actor_id,
        target_id=target_id,
        target_type=target_type,
        event_type=event_type,
        payload=payload,
        request_id=request_id,
    )
    db.add(event)


def _write_audit_independent(
    event_type: str,
    org_id: str | None,
    actor_id: str | None,
    target_id: str | None,
    payload: dict,
    *,
    target_type: str | None = None,
    request_id: str | None = None,
) -> None:
    """Write an audit event in its own independent transaction.
    Used for events that must persist even when the main transaction rolls back
    (e.g., last_admin.action_blocked, auth.login_failed).
    Best-effort: failures are silently swallowed.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session as SASession

    from app.config import settings

    engine = create_engine(settings.database_url)
    try:
        with engine.begin() as conn:
            with SASession(bind=conn) as sess:
                sess.add(
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
                sess.commit()
    except Exception:
        pass  # Best-effort: audit failure must not affect the caller
    finally:
        engine.dispose()


# ── Email helpers ──────────────────────────────────────────────────────────────


async def send_invitation_email(
    provider: EmailProvider,
    org: Organization,
    invited_by_name: str,
    invitee_email: str,
    role: str,
    token_hex: str,
) -> None:
    html, text = workspace_invitation(org.name, invited_by_name, role, token_hex)
    await provider.send(
        to=invitee_email,
        subject=f"You've been invited to join {org.name} on ExpertSeat",
        html_body=html,
        text_body=text,
        kind="invitation",
    )
