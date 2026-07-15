"""Auth router — 14 endpoints for authentication and session management.

Token delivery policy: access tokens are set ONLY in the HttpOnly es_access cookie.
They never appear in JSON response bodies.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.auth.cookies import (
    _set_access_cookie,
    _set_csrf_cookie,
    clear_auth_cookies,
    set_auth_cookies,
)
from app.auth.csrf import require_csrf
from app.auth.deps import CurrentUser, get_current_user
from app.auth.exceptions import RefreshAccountDisabled, RefreshAccountInvalid, RefreshReplayDetected
from app.auth.ratelimit import auth_rate_limit
from app.database import get_db
from app.email.base import EmailProvider
from app.email.deps import get_email_provider
from app.services import auth as auth_service
from app.services import workspace as workspace_service

router = APIRouter(prefix="/auth", tags=["auth"])

# ── Request/response schemas ──────────────────────────────────────────────────

_PASSWORD_MIN = 12
_PASSWORD_MAX = 128


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=_PASSWORD_MIN, max_length=_PASSWORD_MAX)
    full_name: str = Field(min_length=1, max_length=200)


class VerifyEmailRequest(BaseModel):
    token: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")


class ResendVerificationRequest(BaseModel):
    email: EmailStr


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=_PASSWORD_MAX)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=64, max_length=64)
    new_password: str = Field(min_length=_PASSWORD_MIN, max_length=_PASSWORD_MAX)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=_PASSWORD_MAX)
    new_password: str = Field(min_length=_PASSWORD_MIN, max_length=_PASSWORD_MAX)


class SwitchOrgRequest(BaseModel):
    org_id: str


class UserResponse(BaseModel):
    user_id: str
    email: str
    session_id: str
    org_id: str | None
    role: str


# ── Endpoints ─────────────────────────────────────────────────────────────────


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


@router.post("/register", status_code=201)
async def register(
    body: RegisterRequest,
    request: Request,
    db: Session = Depends(get_db),
    provider: EmailProvider = Depends(get_email_provider),
    _rl: None = Depends(auth_rate_limit("register")),
) -> dict:
    user = auth_service.register_user(
        db,
        email=str(body.email),
        password=body.password,
        full_name=body.full_name,
        request_id=_request_id(request),
    )
    workspace_service.create_organization(db, f"{user.full_name}'s Workspace", user.id)
    token = auth_service.create_email_verification_token(db, user.id)
    db.commit()
    await auth_service.send_verification_email(provider, user, token)
    return {"message": "Registration successful. Please check your email to verify your account."}


@router.post("/verify-email", status_code=200)
async def verify_email(
    body: VerifyEmailRequest,
    request: Request,
    db: Session = Depends(get_db),
    _rl: None = Depends(auth_rate_limit("verify-email")),
) -> dict:
    try:
        auth_service.verify_email_token(db, body.token, request_id=_request_id(request))
        db.commit()
    except HTTPException:
        return {"message": "If that link is valid, your email has been verified."}
    return {"message": "Email verified successfully. You can now sign in."}


@router.post("/resend-verification", status_code=200)
async def resend_verification(
    body: ResendVerificationRequest,
    db: Session = Depends(get_db),
    provider: EmailProvider = Depends(get_email_provider),
    _rl: None = Depends(auth_rate_limit("resend-verification")),
) -> dict:
    user = auth_service.get_user_by_email(db, str(body.email))
    if user and not user.email_verified:
        token = auth_service.create_email_verification_token(db, user.id)
        db.commit()
        await auth_service.send_verification_email(provider, user, token)
    return {"message": "If an unverified account exists for that email, a new link has been sent."}


@router.post("/login", status_code=200)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    _rl: None = Depends(auth_rate_limit("login")),
) -> dict:
    user_agent = request.headers.get("user-agent")
    rid = _request_id(request)
    try:
        tokens = auth_service.login(db, str(body.email), body.password, user_agent, request_id=rid)
    except HTTPException:
        # Write failed-login audit BEFORE re-raising so it is committed.
        # Use the same db session — no DB error occurred, just a business rejection.
        auth_service._write_auth_audit(
            db, None, None, None, "auth.login_failed", {}, request_id=rid
        )
        db.commit()
        raise
    db.commit()
    set_auth_cookies(response, tokens.access_token, tokens.refresh_token_hex, tokens.csrf_value)
    return {"message": "Signed in successfully."}


@router.post("/refresh", status_code=200)
async def refresh(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    es_refresh: str | None = Cookie(None),
    _rl: None = Depends(auth_rate_limit("refresh")),
    _csrf: None = Depends(require_csrf),
) -> dict:
    if not es_refresh:
        raise HTTPException(
            status_code=401,
            detail={"error": "MISSING_TOKEN", "message": "Refresh token required"},
        )
    user_agent = request.headers.get("user-agent")
    rid = _request_id(request)
    try:
        tokens = auth_service.refresh_session(db, es_refresh, user_agent, request_id=rid)
    except RefreshReplayDetected:
        # Family revocation is already staged in the session.
        # Commit it BEFORE returning 401 — this is the key fix.
        db.commit()
        clear_auth_cookies(response)
        raise HTTPException(
            status_code=401,
            detail={
                "error": "REFRESH_TOKEN_REUSED",
                "message": "Refresh token has already been used. All sessions have been revoked.",
            },
        )
    except RefreshAccountDisabled:
        # Family revocation already staged — commit before returning 401
        db.commit()
        clear_auth_cookies(response)
        raise HTTPException(
            status_code=401,
            detail={
                "error": "ACCOUNT_DISABLED",
                "message": "This account has been disabled. All sessions have been revoked.",
            },
        )
    except RefreshAccountInvalid as exc:
        clear_auth_cookies(response)
        raise HTTPException(
            status_code=401,
            detail={"error": exc.error_code, "message": exc.message},
        )
    db.commit()
    set_auth_cookies(response, tokens.access_token, tokens.refresh_token_hex, tokens.csrf_value)
    return {"message": "Session refreshed."}


@router.post("/logout", status_code=200)
async def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
    _csrf: None = Depends(require_csrf),
) -> dict:
    auth_service.logout(
        db,
        current_user.session_id,
        current_user.user_id,
        current_user.org_id or None,
        request_id=_request_id(request),
    )
    db.commit()
    clear_auth_cookies(response)
    return {"message": "Signed out successfully."}


@router.post("/logout-all", status_code=200)
async def logout_all(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
    _csrf: None = Depends(require_csrf),
) -> dict:
    auth_service.logout_all(
        db,
        current_user.user_id,
        current_user.org_id or None,
        request_id=_request_id(request),
    )
    db.commit()
    clear_auth_cookies(response)
    return {"message": "All sessions signed out."}


@router.post("/forgot-password", status_code=200)
async def forgot_password(
    body: ForgotPasswordRequest,
    db: Session = Depends(get_db),
    provider: EmailProvider = Depends(get_email_provider),
    _rl: None = Depends(auth_rate_limit("forgot-password")),
) -> dict:
    user = auth_service.get_user_by_email(db, str(body.email))
    if user and user.is_active:
        reset_token = auth_service.create_password_reset_token(db, user.id)
        db.commit()
        await auth_service.send_password_reset_email(provider, user, reset_token)
    return {"message": "If an account exists for that email, a password reset link has been sent."}


@router.post("/reset-password", status_code=200)
async def reset_password(
    body: ResetPasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
    _rl: None = Depends(auth_rate_limit("reset-password")),
) -> dict:
    auth_service.reset_password(db, body.token, body.new_password, request_id=_request_id(request))
    db.commit()
    return {"message": "Password reset successfully. Please sign in with your new password."}


@router.post("/change-password", status_code=200)
async def change_password(
    body: ChangePasswordRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
    _csrf: None = Depends(require_csrf),
) -> dict:
    user_agent = request.headers.get("user-agent")
    tokens = auth_service.change_password(
        db,
        user_id=current_user.user_id,
        current_session_id=current_user.session_id,
        current_password=body.current_password,
        new_password=body.new_password,
        current_org_id=current_user.org_id or None,
        current_user_agent=user_agent,
        request_id=_request_id(request),
    )
    db.commit()
    # Update cookies with the rotated session tokens
    set_auth_cookies(response, tokens.access_token, tokens.refresh_token_hex, tokens.csrf_value)
    return {"message": "Password changed successfully."}


@router.post("/switch-org", status_code=200)
async def switch_org(
    body: SwitchOrgRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
    _csrf: None = Depends(require_csrf),
) -> dict:
    tokens = auth_service.switch_org(
        db,
        current_user.user_id,
        current_user.session_id,
        body.org_id,
        request_id=_request_id(request),
    )
    db.commit()
    _set_access_cookie(response, tokens.access_token)
    _set_csrf_cookie(response, tokens.csrf_value)
    return {"message": "Workspace switched."}


@router.get("/sessions", status_code=200)
async def list_sessions(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict:
    sessions = auth_service.list_sessions(db, current_user.user_id, current_user.session_id)
    return {"sessions": sessions}


@router.delete("/sessions/{session_id}", status_code=200)
async def revoke_session(
    session_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
    _csrf: None = Depends(require_csrf),
) -> dict:
    auth_service.revoke_session(
        db,
        current_user.user_id,
        session_id,
        current_user.org_id or None,
        request_id=_request_id(request),
    )
    db.commit()
    return {"message": "Session revoked."}


@router.get("/me", status_code=200)
async def me(
    db: Annotated[Session, Depends(get_db)],
    current_user: CurrentUser = Depends(get_current_user),
) -> UserResponse:
    from app.models.user import User

    user = db.query(User).filter(User.id == current_user.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail={"error": "USER_NOT_FOUND"})
    return UserResponse(
        user_id=current_user.user_id,
        email=user.email,
        session_id=current_user.session_id,
        org_id=current_user.org_id,  # None when no active workspace
        role=current_user.role,
    )
