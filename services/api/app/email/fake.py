"""Fake email provider for use in integration tests.

Inject via FastAPI dependency override:
    from app.email.fake import FakeEmailProvider
    fake = FakeEmailProvider()
    app.dependency_overrides[get_email_provider] = lambda: fake

Inspect sent emails via the typed query helpers — do NOT rely on last_to()
ordering, as multiple emails may be sent to the same address in one test.
"""

from dataclasses import dataclass


@dataclass
class SentEmail:
    to: str
    subject: str
    html_body: str
    text_body: str
    kind: str = ""  # "verification" | "password_reset" | "invitation" | ""


class FakeEmailProvider:
    def __init__(self) -> None:
        self.sent: list[SentEmail] = []

    async def send(
        self,
        to: str,
        subject: str,
        html_body: str,
        text_body: str,
        kind: str = "",
    ) -> None:
        self.sent.append(
            SentEmail(to=to, subject=subject, html_body=html_body, text_body=text_body, kind=kind)
        )

    def reset(self) -> None:
        """Clear all recorded emails. Call between tests."""
        self.sent.clear()

    # ── Bulk query helpers ──────────────────────────────────────────────────────

    def messages_for(self, recipient: str) -> list[SentEmail]:
        """Return all emails sent to *recipient* in delivery order."""
        return [e for e in self.sent if e.to == recipient]

    def find_by_to(self, address: str) -> list[SentEmail]:
        """Alias of messages_for() for backwards compatibility."""
        return self.messages_for(address)

    def last_to(self, address: str) -> SentEmail | None:
        """Return the most recently sent email to *address*.

        Prefer the typed helpers below when you need a specific message type —
        relying on delivery order is fragile when multiple emails go to the
        same address within one test.
        """
        matching = self.messages_for(address)
        return matching[-1] if matching else None

    # ── Typed lookup helpers ────────────────────────────────────────────────────

    def latest_message(self, recipient: str, kind: str) -> SentEmail | None:
        """Return the most recently sent email of *kind* to *recipient*."""
        matching = [e for e in self.sent if e.to == recipient and e.kind == kind]
        return matching[-1] if matching else None

    def verification_message_for(self, recipient: str) -> SentEmail | None:
        """Return the most recent email-verification message for *recipient*."""
        return self.latest_message(recipient, "verification")

    def invitation_message_for(self, recipient: str) -> SentEmail | None:
        """Return the most recent workspace-invitation message for *recipient*."""
        return self.latest_message(recipient, "invitation")

    def password_reset_message_for(self, recipient: str) -> SentEmail | None:
        """Return the most recent password-reset message for *recipient*."""
        return self.latest_message(recipient, "password_reset")
