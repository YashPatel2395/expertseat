"""Auth router — 14 endpoints for authentication and session management."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.auth.cookies import clear_auth_cookies, set_auth_cookies
from app.auth.csrf import require_csrf
from app.auth.deps import CurrentUser, get_current_user
from app.auth.ratelimit import auth_rate_limit
from app.database import get_db
from app.email.base import EmailProvider
from app.email.deps import get_email_provider
from app.services import auth as auth_service

router = APIRouter(prefix="/auth", tags=["auth"])

# ── Request/response schemas ──────────────────────────────────────────────────


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=200)


class VerifyEmailRequest(BaseModel):
    email: EmailStr
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class ResendVerificationRequest(BaseModel):
    email: EmailStr


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=64, max_length=64)
    new_password: str = Field(min_length=8, max_length=128)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class SwitchOrgRequest(BaseModel):
    org_id: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    user_id: str
    email: str
    session_id: str
    org_id: str
    role: str


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/register", status_code=201)
async def register(
    body: RegisterRequest,
    request: Request,
    db: Session = Depends(get_db),
    provider: EmailProvider = Depends(get_email_provider),
    _rl: None = Depends(auth_rate_limit("register")),
) -> dict:
    user = auth_service.register_user(
        db, email=str(body.email), password=body.password, full_name=body.full_name
    )
    code = auth_service.create_email_verification_token(db, user.id)
    db.commit()
    await auth_service.send_verification_email(provider, user, code)
    return {"message": "Registration successful. Please check your email for a verification code."}


@router.post("/verify-email", status_code=200)
async def verify_email(
    body: VerifyEmailRequest,
    db: Session = Depends(get_db),
    _rl: None = Depends(auth_rate_limit("verify-email")),
) -> dict:
    user = auth_service.get_user_by_email(db, str(body.email))
    if not user:
        # Consistent response regardless of whether email exists
        return {"message": "If that code is valid, your email has been verified."}
    auth_service.verify_email_code(db, user.id, body.code)
    db.commit()
    return {"message": "Email verified successfully. You can now sign in."}


@router.post("/resend-verification", status_code=200)
async def resend_verification(
    body: ResendVerificationRequest,
    db: Session = Depends(get_db),
    provider: EmailProvider = Depends(get_email_provider),
    _rl: None = Depends(auth_rate_limit("resend-verification")),
) -> dict:
    user = auth_service.get_user_by_email(db, str(body.email))
    # Always return the same response to prevent email enumeration
    if user and not user.email_verified:
        code = auth_service.create_email_verification_token(db, user.id)
        db.commit()
        await auth_service.send_verification_email(provider, user, code)
    return {"message": "If an unverified account exists for that email, a new code has been sent."}


@router.post("/login", status_code=200)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    _rl: None = Depends(auth_rate_limit("login")),
) -> TokenResponse:
    ip = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent")
    tokens = auth_service.login(db, str(body.email), body.password, ip, user_agent)
    db.commit()
    set_auth_cookies(response, tokens.access_token, tokens.refresh_token_hex, tokens.csrf_value)
    return TokenResponse(access_token=tokens.access_token)


@router.post("/refresh", status_code=200)
async def refresh(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    es_refresh: str | None = Cookie(None),
    _rl: None = Depends(auth_rate_limit("refresh")),
) -> TokenResponse:
    if not es_refresh:
        raise HTTPException(
            status_code=401,
            detail={"error": "MISSING_TOKEN", "message": "Refresh token required"},
        )
    ip = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent")
    tokens = auth_service.refresh_session(db, es_refresh, ip, user_agent)
    db.commit()
    # Set new access and csrf cookies; refresh cookie also rotated
    set_auth_cookies(response, tokens.access_token, tokens.refresh_token_hex, tokens.csrf_value)
    return TokenResponse(access_token=tokens.access_token)


@router.post("/logout", status_code=200)
async def logout(
    response: Response,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
    _csrf: None = Depends(require_csrf),
) -> dict:
    auth_service.logout(db, current_user.session_id)
    db.commit()
    clear_auth_cookies(response)
    return {"message": "Signed out successfully."}


@router.post("/logout-all", status_code=200)
async def logout_all(
    response: Response,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
    _csrf: None = Depends(require_csrf),
) -> dict:
    auth_service.logout_all(db, current_user.user_id)
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
    # Always return the same response to prevent email enumeration
    if user and user.is_active:
        reset_token = auth_service.create_password_reset_token(db, user.id)
        db.commit()
        await auth_service.send_password_reset_email(provider, user, reset_token)
    return {"message": "If an account exists for that email, a password reset link has been sent."}


@router.post("/reset-password", status_code=200)
async def reset_password(
    body: ResetPasswordRequest,
    db: Session = Depends(get_db),
    _rl: None = Depends(auth_rate_limit("reset-password")),
) -> dict:
    auth_service.reset_password(db, body.token, body.new_password)
    db.commit()
    return {"message": "Password reset successfully. Please sign in with your new password."}


@router.post("/change-password", status_code=200)
async def change_password(
    body: ChangePasswordRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
    _csrf: None = Depends(require_csrf),
) -> dict:
    auth_service.change_password(db, current_user.user_id, body.current_password, body.new_password)
    db.commit()
    return {"message": "Password changed successfully."}


@router.post("/switch-org", status_code=200)
async def switch_org(
    body: SwitchOrgRequest,
    response: Response,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
    _csrf: None = Depends(require_csrf),
) -> TokenResponse:
    tokens = auth_service.switch_org(db, current_user.user_id, current_user.session_id, body.org_id)
    db.commit()
    # Only update access and csrf cookies; refresh token is unchanged
    from app.auth.cookies import _set_access_cookie, _set_csrf_cookie

    _set_access_cookie(response, tokens.access_token)
    _set_csrf_cookie(response, tokens.csrf_value)
    return TokenResponse(access_token=tokens.access_token)


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
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
    _csrf: None = Depends(require_csrf),
) -> dict:
    auth_service.revoke_session(db, current_user.user_id, session_id)
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
        org_id=current_user.org_id,
        role=current_user.role,
    )
