"""FastAPI dependency for the email provider.

Override this in integration tests:
    from app.email.fake import FakeEmailProvider
    from app.email.deps import get_email_provider
    fake = FakeEmailProvider()
    app.dependency_overrides[get_email_provider] = lambda: fake
"""

from app.config import settings
from app.email.base import EmailProvider
from app.email.smtp import SmtpEmailProvider


def get_email_provider() -> EmailProvider:
    return SmtpEmailProvider(
        host=settings.mailpit_host,
        port=settings.mailpit_port,
        from_address=settings.email_from,
    )
