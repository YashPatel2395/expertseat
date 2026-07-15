"""Email provider Protocol interface.

All email providers implement this Protocol. The concrete implementation
is selected via the get_email_provider() FastAPI dependency in deps.py.
Tests override that dependency with FakeEmailProvider.
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class EmailProvider(Protocol):
    async def send(
        self,
        to: str,
        subject: str,
        html_body: str,
        text_body: str,
        kind: str = "",
    ) -> None:
        """Send an email.

        Args:
            to: Recipient email address.
            subject: Email subject line.
            html_body: HTML content of the email body.
            text_body: Plain-text content of the email body (fallback).
            kind: Message category ("verification" | "password_reset" | "invitation").
                  Ignored by production providers; used by FakeEmailProvider for
                  test assertions without relying on delivery order.

        Raises:
            Exception: Any delivery failure. Callers should handle or log.
        """
        ...
