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
) -> dict:
    invitation = ws.create_invitation(
        db, ctx.org_id, str(body.email), body.role, ctx.user_id, request_id=_request_id(request)
    )
    # Attempt email delivery BEFORE committing so delivery status is committed together
    token_hex = getattr(invitation, "_plaintext_token", "")
    delivery_status = "pending"
    failure_code: str | None = None
    if token_hex:
        org = ws.get_organization(db, ctx.org_id)
        from app.models.user import User

        actor = db.query(User).filter(User.id == ctx.user_id).first()
        actor_name = actor.full_name if actor else "Someone"
        try:
            await ws.send_invitation_email(
                provider, org, actor_name, invitation.email, invitation.role, token_hex
            )
            delivery_status = "sent"
        except Exception:
            logger.warning(
                "Invitation email delivery failed",
                invitation_id=invitation.id,
                email=invitation.email,
            )
            delivery_status = "failed"
            failure_code = "SMTP_ERROR"
    ws.update_invitation_delivery(db, invitation.id, delivery_status, failure_code)
    db.commit()
    return {
        "id": invitation.id,
        "email": invitation.email,
        "role": invitation.role,
        "delivery_status": delivery_status,
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
) -> dict:
    invitation = ws.resend_invitation(
        db, ctx.org_id, invitation_id, ctx.user_id, request_id=_request_id(request)
    )
    token_hex = getattr(invitation, "_plaintext_token", "")
    delivery_status = "pending"
    failure_code: str | None = None
    if token_hex:
        org = ws.get_organization(db, ctx.org_id)
        from app.models.user import User

        actor = db.query(User).filter(User.id == ctx.user_id).first()
        actor_name = actor.full_name if actor else "Someone"
        try:
            await ws.send_invitation_email(
                provider, org, actor_name, invitation.email, invitation.role, token_hex
            )
            delivery_status = "sent"
        except Exception:
            delivery_status = "failed"
            failure_code = "SMTP_ERROR"
    ws.update_invitation_delivery(db, invitation.id, delivery_status, failure_code)
    db.commit()
    return {"message": "Invitation resent.", "delivery_status": delivery_status}


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
) -> dict:
    """Accept an invitation as a new (unregistered) user.

    Creates the user account, treats token possession as email verification,
    creates the membership, and auto-signs the user in.
    """
    user_agent = request.headers.get("user-agent")
    org, membership, tokens = ws.accept_invitation_new_user(
        db,
        body.token,
        body.full_name,
        body.password,
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
