"""JWT access token and opaque refresh token utilities."""

from datetime import UTC, datetime

import jwt

from app.config import settings


def create_access_token(
    user_id: str,
    session_id: str,
    org_id: str,
    membership_id: str,
    role: str,
    jti: str,
) -> str:
    """Create a signed JWT access token with workspace claims.

    Claims:
        iss  — issuer: "expertseat"
        aud  — audience: "expertseat-api"
        sub  — user_id
        sid  — auth_session id
        org  — org_id (active organization)
        mid  — membership_id
        role — "admin" | "recruiter" | "reviewer"
        iat  — issued-at (UTC)
        exp  — expiry (UTC, access_token_ttl seconds from now)
        jti  — unique token ID (for future revocation support)
    """
    now = datetime.now(tz=UTC)
    payload = {
        "iss": "expertseat",
        "aud": "expertseat-api",
        "sub": user_id,
        "sid": session_id,
        "org": org_id,
        "mid": membership_id,
        "role": role,
        "iat": now,
        "exp": now.timestamp() + settings.access_token_ttl,
        "jti": jti,
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def decode_access_token(token: str) -> dict:
    """Decode and validate a JWT access token.

    Raises:
        jwt.ExpiredSignatureError  — token is expired
        jwt.InvalidTokenError      — any other validation failure
    """
    return jwt.decode(
        token,
        settings.secret_key,
        algorithms=["HS256"],
        audience="expertseat-api",
        issuer="expertseat",
    )
