# ADR-004: Email Provider Abstraction

**Status**: Accepted  
**Date**: 2026-07-13  
**Milestone**: 1

---

## Context

Milestone 1 requires email delivery for:
- Email address verification (6-digit code)
- Password reset (link with token)
- Organization invitations (link with token)

The email provider must:
1. Be replaceable without changing calling code (different SMTP host, future SaaS provider)
2. Be testable without sending real emails
3. Not block the FastAPI event loop
4. Not require a new heavy dependency in Milestone 1

Options considered:
- **aiosmtplib** — async SMTP, requires new dependency
- **smtplib (stdlib)** via `asyncio.to_thread()` — no dependency, non-blocking via thread pool
- **SendGrid / Postmark / Resend SDK** — SaaS provider, requires API key management
- **httpx-based custom client** — flexible but premature

---

## Decision

Use a **Protocol-based provider interface** with two implementations:

### Interface

```python
# app/email/base.py
from typing import Protocol

class EmailProvider(Protocol):
    async def send(
        self,
        to: str,
        subject: str,
        html_body: str,
        text_body: str,
    ) -> None: ...
```

### SMTP Implementation (development and production)

```python
# app/email/smtp.py
import asyncio
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

class SmtpEmailProvider:
    def __init__(self, host: str, port: int, from_address: str): ...

    async def send(self, to, subject, html_body, text_body):
        await asyncio.to_thread(self._send_sync, to, subject, html_body, text_body)

    def _send_sync(self, to, subject, html_body, text_body):
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self.from_address
        msg["To"] = to
        msg.attach(MIMEText(text_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))
        with smtplib.SMTP(self.host, self.port) as server:
            server.sendmail(self.from_address, [to], msg.as_string())
```

`asyncio.to_thread()` runs the blocking SMTP call in the default thread pool executor, so it does not block the FastAPI event loop. No persistent connection — a new connection is opened per send (acceptable for Milestone 1 send volumes).

### Fake Implementation (tests)

```python
# app/email/fake.py
class FakeEmailProvider:
    def __init__(self):
        self.sent: list[dict] = []

    async def send(self, to, subject, html_body, text_body):
        self.sent.append({"to": to, "subject": subject, "html_body": html_body})
```

### Dependency injection

```python
# app/email/deps.py
def get_email_provider() -> EmailProvider:
    return SmtpEmailProvider(
        host=settings.mailpit_host,
        port=settings.mailpit_port,
        from_address=settings.email_from,
    )
```

Route handlers: `provider: EmailProvider = Depends(get_email_provider)`.

Integration tests override: `app.dependency_overrides[get_email_provider] = lambda: fake_provider`.

### Local development

Mailpit is added to `infrastructure/docker-compose.yml`. It provides:
- SMTP server on `127.0.0.1:1025` (no authentication required)
- Web UI on `127.0.0.1:8025` to inspect sent emails
- Playwright E2E tests use the Mailpit API (`GET /api/v1/messages`) to retrieve email content

---

## Consequences

- No new runtime dependency for Milestone 1 email (smtplib is stdlib)
- Email provider is swappable: `get_email_provider` can return a Postmark/SendGrid provider in a future milestone by changing one function
- Fake provider in tests provides full inspection of sent email content
- `asyncio.to_thread()` adds slight overhead (thread handoff) but is negligible at email send frequencies

---

## Rejected Alternatives

**aiosmtplib**: Adds a dependency for functionality available in stdlib. Deferred to a future milestone if async SMTP becomes a performance concern.

**SaaS provider (SendGrid, Postmark)**: Requires API key, adds billing complexity, premature for Milestone 1 (no production send volumes yet).

**Background task queue (Celery, ARQ)**: Over-engineering for Milestone 1. Email sends are not high-volume. Can be added later if reliability (retry logic, dead-letter queues) becomes a requirement.
