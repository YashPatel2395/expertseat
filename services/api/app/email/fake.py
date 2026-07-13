"""Fake email provider for use in integration tests.

Inject via FastAPI dependency override:
    from app.email.fake import FakeEmailProvider
    fake = FakeEmailProvider()
    app.dependency_overrides[get_email_provider] = lambda: fake

Inspect sent emails via fake.sent — a list of dicts with keys:
    to, subject, html_body, text_body
"""

from dataclasses import dataclass


@dataclass
class SentEmail:
    to: str
    subject: str
    html_body: str
    text_body: str


class FakeEmailProvider:
    def __init__(self) -> None:
        self.sent: list[SentEmail] = []

    async def send(
        self,
        to: str,
        subject: str,
        html_body: str,
        text_body: str,
    ) -> None:
        self.sent.append(
            SentEmail(to=to, subject=subject, html_body=html_body, text_body=text_body)
        )

    def reset(self) -> None:
        """Clear all recorded emails. Call between tests."""
        self.sent.clear()

    def find_by_to(self, address: str) -> list[SentEmail]:
        """Return all emails sent to the given address."""
        return [e for e in self.sent if e.to == address]

    def last_to(self, address: str) -> SentEmail | None:
        """Return the most recent email sent to the given address."""
        matching = self.find_by_to(address)
        return matching[-1] if matching else None
