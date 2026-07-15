"""Workspace router — endpoints for organization and member management."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.auth.cookies import set_auth_cookies
from app.auth.csrf import require_csrf
from app.auth.deps import WorkspaceContext, get_current_user, get_workspace_context
from app.auth.policy import check_can_manage_member, require_role
from app.auth.ratelimit import invitation_rate_limit
from app.database import get_db
from app.email.base import EmailProvider
from app.email.deps import get_email_provider
from app.services import workspace as ws

router = APIRouter(prefix="/workspace", tags=["workspace"])
logger = structlog.get_logger()

# ── Schemas ───────────────────────────────────────────────────────────────────

_PASSWORD_MIN = 12
_PASSWORD_MAX = 128


class CreateOrgRequest(BaseModel):
    name: str = Field(min_length=2, max_length=200)


class UpdateOrgRequest(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=200)
    slug: str | None = Field(None, min_length=3, max_length=48)


class UpdateMemberRoleRequest(BaseModel):
    role: str


class SetMemberActiveRequest(BaseModel):
    is_active: bool


class InviteRequest(BaseModel):
    email: EmailStr
    role: str = Field(pattern=r"^(admin|recruiter|reviewer)$")


class AcceptInvitationRequest(BaseModel):
    token: str = Field(min_length=64, max_length=64)


class AcceptInvitationNewUserRequest(BaseModel):
    token: str = Field(min_length=64, max_length=64)
    full_name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=_PASSWORD_MIN, max_length=_PASSWORD_MAX)
    terms_accepted: bool
    privacy_notice_accepted: bool
    terms_version: str = Field(min_length=1, max_length=50)
    privacy_notice_version: str = Field(min_length=1, max_length=50)


# ── Helper ────────────────────────────────────────────────────────────────────


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


# ── Organization endpoints ────────────────────────────────────────────────────


@router.post("/organizations", status_code=201)
async def create_organization(
    body: CreateOrgRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: WorkspaceContext = Depends(get_current_user),
    _csrf: None = Depends(require_csrf),
) -> dict:
    org = ws.create_organization(
        db, name=body.name, creator_user_id=current_user.user_id, request_id=_request_id(request)
    )
    db.commit()
    return {"id": org.id, "name": org.name, "slug": org.slug}


@router.get("/organizations", status_code=200)
async def list_organizations(
    db: Session = Depends(get_db),
    current_user: WorkspaceContext = Depends(get_current_user),
) -> dict:
    orgs = ws.list_user_organizations(db, current_user.user_id)
    return {"organizations": [{"id": o.id, "name": o.name, "slug": o.slug} for o in orgs]}


@router.get("/organizations/{org_id}", status_code=200)
async def get_organization(
    org_id: str,
    db: Session = Depends(get_db),
    ctx: WorkspaceContext = Depends(get_workspace_context),
) -> dict:
    if org_id != ctx.org_id:
        raise HTTPException(
            status_code=403,
            detail={"error": "INSUFFICIENT_ROLE", "message": "Access denied"},
        )
    org = ws.get_organization(db, org_id)
    return {"id": org.id, "name": org.name, "slug": org.slug}


# ── Member endpoints ──────────────────────────────────────────────────────────


@router.get("/members", status_code=200)
async def list_members(
    db: Session = Depends(get_db),
    ctx: WorkspaceContext = Depends(get_workspace_context),
) -> dict:
    members = ws.list_members(db, ctx.org_id)
    return {"members": members}


@router.get("/members/{user_id}", status_code=200)
async def get_member(
    user_id: str,
    db: Session = Depends(get_db),
    ctx: WorkspaceContext = Depends(get_workspace_context),
) -> dict:
    return ws.get_member(db, ctx.org_id, user_id)


@router.patch("/members/{user_id}", status_code=200)
async def update_member_role(
    user_id: str,
    body: UpdateMemberRoleRequest,
    request: Request,
    db: Session = Depends(get_db),
    ctx: WorkspaceContext = Depends(get_workspace_context),
    _role: None = Depends(require_role("admin")),
    _csrf: None = Depends(require_csrf),
) -> dict:
    check_can_manage_member(ctx.role, body.role)
    result = ws.update_member_role(
        db, ctx.org_id, user_id, body.role, ctx.user_id, request_id=_request_id(request)
    )
    db.commit()
    return result


@router.delete("/members/{user_id}", status_code=200)
async def remove_member(
    user_id: str,
    request: Request,
    db: Session = Depends(get_db),
    ctx: WorkspaceContext = Depends(get_workspace_context),
    _role: None = Depends(require_role("admin")),
    _csrf: None = Depends(require_csrf),
) -> dict:
    ws.remove_member(db, ctx.org_id, user_id, ctx.user_id, request_id=_request_id(request))
    db.commit()
    return {"message": "Member removed."}


@router.patch("/members/{user_id}/status", status_code=200)
async def set_member_status(
    user_id: str,
    body: SetMemberActiveRequest,
    request: Request,
    db: Session = Depends(get_db),
    ctx: WorkspaceContext = Depends(get_workspace_context),
    _role: None = Depends(require_role("admin")),
    _csrf: None = Depends(require_csrf),
) -> dict:
    result = ws.set_member_active(
        db, ctx.org_id, user_id, body.is_active, ctx.user_id, request_id=_request_id(request)
    )
    db.commit()
    return result


# ── Invitation endpoints ──────────────────────────────────────────────────────


@router.get("/invitations", status_code=200)
async def list_invitations(
    db: Session = Depends(get_db),
    ctx: WorkspaceContext = Depends(get_workspace_context),
    _role: None = Depends(require_role("admin")),
) -> dict:
    invitations = ws.list_invitations(db, ctx.org_id)
    return {"invitations": invitations}


@router.post("/invitations", status_code=201)
async def create_invitation(
    body: InviteRequest,
    request: Request,
    db: Session = Depends(get_db),
    ctx: WorkspaceContext = Depends(get_workspace_context),
    provider: EmailProvider = Depends(get_email_provider),
    _role: None = Depends(require_role("admin")),
    _csrf: None = Depends(require_csrf),
    _rl: None = Depends(invitation_rate_limit("invitation-create")),
) -> dict:
    from app.email.outbox import attempt_delivery_after_commit, enqueue_email
    from app.email.templates import workspace_invitation
    from app.models.user import User

    invitation = ws.create_invitation(
        db, ctx.org_id, str(body.email), body.role, ctx.user_id, request_id=_request_id(request)
    )
    token_hex = getattr(invitation, "_plaintext_token", "")
    outbox_row_id: str | None = None
    if token_hex:
        org = ws.get_organization(db, ctx.org_id)
        actor = db.query(User).filter(User.id == ctx.user_id).first()
        actor_name = actor.full_name if actor else "Someone"
        html, text = workspace_invitation(org.name, actor_name, invitation.role, token_hex)
        outbox_row = enqueue_email(
            db,
            to=invitation.email,
            subject=f"You've been invited to join {org.name} on ExpertSeat",
            html_body=html,
            text_body=text,
            kind="invitation",
        )
        ws.update_invitation_delivery(db, invitation.id, "queued", None)
        # Commit invitation + outbox row atomically BEFORE attempting delivery.
        # The outbox row guarantees durability: SMTP failure leaves a retryable row.
        db.commit()
        outbox_row_id = outbox_row.id
    else:
        ws.update_invitation_delivery(db, invitation.id, "queued", None)
        db.commit()

    # Post-commit delivery using Tx A/B pattern.
    # HTTP response is always "queued" regardless of SMTP outcome (enumeration resistance).
    if outbox_row_id:
        await attempt_delivery_after_commit(outbox_row_id, provider)

    return {
        "id": invitation.id,
        "email": invitation.email,
        "role": invitation.role,
        "delivery_status": "queued",
    }


@router.post("/invitations/{invitation_id}/resend", status_code=200)
async def resend_invitation(
    invitation_id: str,
    request: Request,
    db: Session = Depends(get_db),
    ctx: WorkspaceContext = Depends(get_workspace_context),
    provider: EmailProvider = Depends(get_email_provider),
    _role: None = Depends(require_role("admin")),
    _csrf: None = Depends(require_csrf),
    _rl: None = Depends(invitation_rate_limit("invitation-resend")),
) -> dict:
    from app.email.outbox import attempt_delivery_after_commit, enqueue_email
    from app.email.templates import workspace_invitation
    from app.models.user import User

    invitation = ws.resend_invitation(
        db, ctx.org_id, invitation_id, ctx.user_id, request_id=_request_id(request)
    )
    token_hex = getattr(invitation, "_plaintext_token", "")
    outbox_row_id: str | None = None
    if token_hex:
        org = ws.get_organization(db, ctx.org_id)
        actor = db.query(User).filter(User.id == ctx.user_id).first()
        actor_name = actor.full_name if actor else "Someone"
        html, text = workspace_invitation(org.name, actor_name, invitation.role, token_hex)
        outbox_row = enqueue_email(
            db,
            to=invitation.email,
            subject=f"You've been invited to join {org.name} on ExpertSeat",
            html_body=html,
            text_body=text,
            kind="invitation",
        )
        ws.update_invitation_delivery(db, invitation.id, "queued", None)
        db.commit()
        outbox_row_id = outbox_row.id
    else:
        ws.update_invitation_delivery(db, invitation.id, "queued", None)
        db.commit()

    if outbox_row_id:
        await attempt_delivery_after_commit(outbox_row_id, provider)

    return {"message": "Invitation resent.", "delivery_status": "queued"}


@router.delete("/invitations/{invitation_id}", status_code=200)
async def revoke_invitation(
    invitation_id: str,
    request: Request,
    db: Session = Depends(get_db),
    ctx: WorkspaceContext = Depends(get_workspace_context),
    _role: None = Depends(require_role("admin")),
    _csrf: None = Depends(require_csrf),
) -> dict:
    ws.revoke_invitation(
        db, ctx.org_id, invitation_id, ctx.user_id, request_id=_request_id(request)
    )
    db.commit()
    return {"message": "Invitation revoked."}


@router.get("/invitations/preview", status_code=200)
async def preview_invitation(
    token: str = Query(min_length=64, max_length=64),
    db: Session = Depends(get_db),
) -> dict:
    """Return safe preview of an invitation (no auth required).

    Reveals only: organization name, role, masked email, expiry.
    Never reveals the full invitee email address.
    """
    return ws.preview_invitation(db, token)


@router.post("/invitations/accept", status_code=200)
async def accept_invitation(
    body: AcceptInvitationRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: WorkspaceContext = Depends(get_current_user),
    _csrf: None = Depends(require_csrf),
    _rl: None = Depends(invitation_rate_limit("invitation-accept")),
) -> dict:
    org, membership = ws.accept_invitation(
        db, body.token, current_user.user_id, request_id=_request_id(request)
    )
    db.commit()
    return {
        "message": "Invitation accepted.",
        "organization": {"id": org.id, "name": org.name, "slug": org.slug},
        "role": membership.role,
    }


@router.post("/invitations/accept-new", status_code=201)
async def accept_invitation_new_user(
    body: AcceptInvitationNewUserRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    _rl: None = Depends(invitation_rate_limit("invitation-accept-new")),
) -> dict:
    """Accept an invitation as a new (unregistered) user.

    Creates the user account, treats token possession as email verification,
    creates the membership, records versioned consent, and auto-signs the user in.

    Consent is required: terms_accepted and privacy_notice_accepted must both be True,
    and the provided version strings must be in the currently supported versions list.
    """
    from app.config import settings as _settings

    if not body.terms_accepted:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "TERMS_NOT_ACCEPTED",
                "message": "You must accept the terms of service",
            },
        )
    if not body.privacy_notice_accepted:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "PRIVACY_NOT_ACCEPTED",
                "message": "You must accept the privacy notice",
            },
        )
    if body.terms_version not in _settings.supported_terms_versions:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "UNSUPPORTED_TERMS_VERSION",
                "message": f"Terms version '{body.terms_version}' is not supported",
            },
        )
    if body.privacy_notice_version not in _settings.supported_privacy_versions:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "UNSUPPORTED_PRIVACY_VERSION",
                "message": (
                    f"Privacy notice version '{body.privacy_notice_version}' is not supported"
                ),
            },
        )

    user_agent = request.headers.get("user-agent")
    org, membership, tokens = ws.accept_invitation_new_user(
        db,
        body.token,
        body.full_name,
        body.password,
        terms_version=body.terms_version,
        privacy_notice_version=body.privacy_notice_version,
        user_agent=user_agent,
        request_id=_request_id(request),
    )
    db.commit()
    set_auth_cookies(response, tokens.access_token, tokens.refresh_token_hex, tokens.csrf_value)
    return {
        "message": "Account created and invitation accepted.",
        "organization": {"id": org.id, "name": org.name, "slug": org.slug},
        "role": membership.role,
    }


# ── Settings endpoints ────────────────────────────────────────────────────────


@router.get("/settings", status_code=200)
async def get_settings(
    db: Session = Depends(get_db),
    ctx: WorkspaceContext = Depends(get_workspace_context),
) -> dict:
    org = ws.get_organization(db, ctx.org_id)
    return {"id": org.id, "name": org.name, "slug": org.slug}


@router.patch("/settings", status_code=200)
async def update_settings(
    body: UpdateOrgRequest,
    request: Request,
    db: Session = Depends(get_db),
    ctx: WorkspaceContext = Depends(get_workspace_context),
    _role: None = Depends(require_role("admin")),
    _csrf: None = Depends(require_csrf),
) -> dict:
    org = ws.update_organization(
        db, ctx.org_id, ctx.user_id, body.name, body.slug, request_id=_request_id(request)
    )
    db.commit()
    return {"id": org.id, "name": org.name, "slug": org.slug}


# ── Audit log endpoint ────────────────────────────────────────────────────────


@router.get("/audit", status_code=200)
async def get_audit_log(
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    ctx: WorkspaceContext = Depends(get_workspace_context),
    _role: None = Depends(require_role("admin")),
) -> dict:
    events = ws.get_audit_log(db, ctx.org_id, limit=min(limit, 200), offset=offset)
    return {"events": events}
