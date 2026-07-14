"""Unit tests for FakeEmailProvider.

Verifies that the typed lookup helpers correctly filter by kind and that
delivery order is preserved. These tests do not require a database or Redis.
"""

import asyncio

import pytest

from app.email.fake import FakeEmailProvider, SentEmail


def _send(provider: FakeEmailProvider, to: str, kind: str, subject: str = "s") -> None:
    asyncio.run(provider.send(to=to, subject=subject, html_body="h", text_body="t", kind=kind))


@pytest.fixture
def provider() -> FakeEmailProvider:
    return FakeEmailProvider()


# ── messages_for ───────────────────────────────────────────────────────────────


def test_messages_for_returns_all_emails_to_recipient(provider: FakeEmailProvider) -> None:
    _send(provider, "a@x.com", "verification")
    _send(provider, "a@x.com", "invitation")
    _send(provider, "b@x.com", "verification")
    assert len(provider.messages_for("a@x.com")) == 2
    assert len(provider.messages_for("b@x.com")) == 1


def test_messages_for_unknown_recipient_returns_empty(provider: FakeEmailProvider) -> None:
    assert provider.messages_for("nobody@x.com") == []


# ── latest_message ─────────────────────────────────────────────────────────────


def test_latest_message_returns_none_for_unknown_recipient(provider: FakeEmailProvider) -> None:
    assert provider.latest_message("nobody@x.com", "verification") is None


def test_latest_message_filters_by_kind(provider: FakeEmailProvider) -> None:
    _send(provider, "a@x.com", "invitation", subject="invite1")
    _send(provider, "a@x.com", "verification", subject="verify1")
    _send(provider, "a@x.com", "invitation", subject="invite2")

    msg = provider.latest_message("a@x.com", "verification")
    assert msg is not None
    assert msg.subject == "verify1"


def test_latest_message_returns_most_recent_of_kind(provider: FakeEmailProvider) -> None:
    _send(provider, "a@x.com", "verification", subject="first")
    _send(provider, "a@x.com", "verification", subject="second")

    msg = provider.latest_message("a@x.com", "verification")
    assert msg is not None
    assert msg.subject == "second"


# ── typed helpers ──────────────────────────────────────────────────────────────


def test_verification_message_for_returns_only_verification(provider: FakeEmailProvider) -> None:
    _send(provider, "u@x.com", "invitation")
    _send(provider, "u@x.com", "verification", subject="verify")
    msg = provider.verification_message_for("u@x.com")
    assert msg is not None
    assert msg.subject == "verify"


def test_invitation_message_for_returns_only_invitation(provider: FakeEmailProvider) -> None:
    _send(provider, "u@x.com", "verification")
    _send(provider, "u@x.com", "invitation", subject="invite")
    msg = provider.invitation_message_for("u@x.com")
    assert msg is not None
    assert msg.subject == "invite"


def test_password_reset_message_for_returns_only_reset(provider: FakeEmailProvider) -> None:
    _send(provider, "u@x.com", "verification")
    _send(provider, "u@x.com", "password_reset", subject="reset")
    msg = provider.password_reset_message_for("u@x.com")
    assert msg is not None
    assert msg.subject == "reset"


# ── reset ──────────────────────────────────────────────────────────────────────


def test_reset_clears_all_sent_emails(provider: FakeEmailProvider) -> None:
    _send(provider, "u@x.com", "verification")
    _send(provider, "u@x.com", "invitation")
    provider.reset()

    assert provider.messages_for("u@x.com") == []
    assert provider.verification_message_for("u@x.com") is None
    assert provider.invitation_message_for("u@x.com") is None
    assert provider.last_to("u@x.com") is None


# ── SentEmail dataclass ────────────────────────────────────────────────────────


def test_sent_email_kind_defaults_to_empty_string() -> None:
    email = SentEmail(to="a@x.com", subject="s", html_body="h", text_body="t")
    assert email.kind == ""
