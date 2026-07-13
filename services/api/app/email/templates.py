"""Email body templates.

All template functions return a tuple of (html_body, text_body).
Templates are inline strings — no template engine dependency in Milestone 1.
"""

from app.config import settings

_FRONTEND_BASE = (
    settings.cors_allowed_origins[0] if settings.cors_allowed_origins else "http://localhost:3000"
)


def email_verification(full_name: str, code: str) -> tuple[str, str]:
    html = f"""
<!DOCTYPE html>
<html>
<body>
<p>Hi {full_name},</p>
<p>Your ExpertSeat verification code is:</p>
<h2 style="letter-spacing: 4px;">{code}</h2>
<p>This code expires in 24 hours.</p>
<p>If you did not create an account, you can ignore this email.</p>
</body>
</html>
""".strip()

    text = (
        f"Hi {full_name},\n\n"
        f"Your ExpertSeat verification code is: {code}\n\n"
        f"This code expires in 24 hours.\n\n"
        f"If you did not create an account, you can ignore this email."
    )
    return html, text


def password_reset(full_name: str, reset_token: str) -> tuple[str, str]:
    link = f"{_FRONTEND_BASE}/reset-password?token={reset_token}"
    html = f"""
<!DOCTYPE html>
<html>
<body>
<p>Hi {full_name},</p>
<p>We received a request to reset your ExpertSeat password.</p>
<p><a href="{link}">Reset your password</a></p>
<p>This link expires in 1 hour and can only be used once.</p>
<p>If you did not request a password reset, you can ignore this email.</p>
</body>
</html>
""".strip()

    text = (
        f"Hi {full_name},\n\n"
        f"We received a request to reset your ExpertSeat password.\n\n"
        f"Reset your password: {link}\n\n"
        f"This link expires in 1 hour and can only be used once.\n\n"
        f"If you did not request a password reset, you can ignore this email."
    )
    return html, text


def workspace_invitation(
    org_name: str, invited_by_name: str, role: str, invite_token: str
) -> tuple[str, str]:
    link = f"{_FRONTEND_BASE}/invite/{invite_token}"
    html = f"""
<!DOCTYPE html>
<html>
<body>
<p>{invited_by_name} has invited you to join <strong>{org_name}</strong> on ExpertSeat
as a <strong>{role}</strong>.</p>
<p><a href="{link}">Accept invitation</a></p>
<p>This invitation expires in 7 days.</p>
</body>
</html>
""".strip()

    text = (
        f"{invited_by_name} has invited you to join {org_name} on ExpertSeat as a {role}.\n\n"
        f"Accept invitation: {link}\n\n"
        f"This invitation expires in 7 days."
    )
    return html, text
