"""Cookie management for authentication tokens.

Cookie inventory:
  es_access  — JWT access token. HttpOnly, path=/api/v1
  es_refresh — Opaque refresh token (hex). HttpOnly, path=/api/v1/auth
  es_csrf    — CSRF double-submit value (hex). NOT HttpOnly, path=/
"""

from fastapi import Response

from app.config import settings

_SECURE = settings.app_env == "production"


def set_auth_cookies(
    response: Response,
    access_token: str,
    refresh_token_hex: str,
    csrf_value: str,
) -> None:
    """Set all three auth cookies on the response."""
    _set_access_cookie(response, access_token)
    _set_refresh_cookie(response, refresh_token_hex)
    _set_csrf_cookie(response, csrf_value)


def _set_access_cookie(response: Response, access_token: str) -> None:
    response.set_cookie(
        key="es_access",
        value=access_token,
        httponly=True,
        secure=_SECURE,
        samesite="lax",
        path="/api/v1",
        max_age=settings.access_token_ttl,
    )


def _set_refresh_cookie(response: Response, refresh_token_hex: str) -> None:
    response.set_cookie(
        key="es_refresh",
        value=refresh_token_hex,
        httponly=True,
        secure=_SECURE,
        samesite="lax",
        path="/api/v1/auth",
        max_age=settings.refresh_token_ttl,
    )


def _set_csrf_cookie(response: Response, csrf_value: str) -> None:
    response.set_cookie(
        key="es_csrf",
        value=csrf_value,
        httponly=False,  # Must be readable by JavaScript
        secure=_SECURE,
        samesite="lax",
        path="/",
        max_age=settings.access_token_ttl,
    )


def clear_auth_cookies(response: Response) -> None:
    """Clear all auth cookies (used on logout)."""
    response.delete_cookie("es_access", path="/api/v1")
    response.delete_cookie("es_refresh", path="/api/v1/auth")
    response.delete_cookie("es_csrf", path="/")
