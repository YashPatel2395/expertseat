"""SMTP email provider using Python stdlib smtplib.

smtplib is synchronous. We run it in asyncio's thread pool via
asyncio.to_thread() so it does not block the FastAPI event loop.

A new SMTP connection is opened per send. This is acceptable for
Milestone 1 send volumes (transactional email only — verification,
password reset, invitations). Persistent connections can be added
later if throughput warrants it.
"""

import asyncio
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


class SmtpEmailProvider:
    def __init__(self, host: str, port: int, from_address: str) -> None:
        self.host = host
        self.port = port
        self.from_address = from_address

    async def send(
        self,
        to: str,
        subject: str,
        html_body: str,
        text_body: str,
        kind: str = "",  # noqa: ARG002 — informational only, not used by SMTP
    ) -> None:
        await asyncio.to_thread(self._send_sync, to, subject, html_body, text_body)

    def _send_sync(self, to: str, subject: str, html_body: str, text_body: str) -> None:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self.from_address
        msg["To"] = to
        msg.attach(MIMEText(text_body, "plain", "utf-8"))
        msg.attach(MIMEText(html_body, "html", "utf-8"))
        with smtplib.SMTP(self.host, self.port) as server:
            server.sendmail(self.from_address, [to], msg.as_string())
