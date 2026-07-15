"""JWT access token and opaque refresh token utilities."""

from datetime import UTC, datetime

import jwt

from app.config import settings


def create_access_token(
    user_id: str,
    session_id: str,
    org_id: str | None,
    membership_id: str | None,
    role: str,
    jti: str,
) -> str:
    """Create a signed JWT access token with workspace claims.

    Claims:
        iss  — issuer: "expertseat"
        aud  — audience: "expertseat-api"
        sub  — user_id
        sid  — auth_session id
        org  — org_id (active organization) or null for no-workspace sessions
        mid  — membership_id or null for no-workspace sessions
        role — "admin" | "recruiter" | "reviewer" or "" for no-workspace sessions
        iat  — issued-at (UTC)
        exp  — expiry (UTC, access_token_ttl seconds from now)
        jti  — unique token ID (for future revocation support)

    Workspace context invariants enforced here:
      - org and mid must both be non-null or both be null (no partial context).
      - Empty strings are rejected — None is the canonical no-workspace sentinel.
    """
    if org_id == "" or membership_id == "":
        raise ValueError(
            "org_id and membership_id must be None (not empty string) for no-workspace sessions"
        )
    if (org_id is None) != (membership_id is None):
        raise ValueError(
            "org_id and membership_id must both be set or both be None (mismatched presence)"
        )
    now = datetime.now(tz=UTC)
    payload = {
        "iss": "expertseat",
        "aud": "expertseat-api",
        "sub": user_id,
        "sid": session_id,
        "org": org_id,  # None serializes as JSON null
        "mid": membership_id,  # None serializes as JSON null
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
