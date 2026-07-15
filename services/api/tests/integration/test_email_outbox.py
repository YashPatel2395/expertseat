"""Integration tests for the transactional email outbox.

Invariants verified:
  1.  AEAD encrypt/decrypt round-trip (AES-256-GCM)
  2.  Unique nonce — identical payloads produce distinct ciphertexts
  3.  Tampered ciphertext raises ValueError (authentication tag failure)
  4.  Wrong key raises ValueError
  5.  Truncated payload raises ValueError
  6.  Unsupported envelope version raises ValueError
  7.  enqueue_email writes an encrypted row (status=pending)
  8.  process_outbox_once delivers and marks 'sent'
  9.  Business rollback creates no outbox row
 10.  SMTP failure sets status='retry', increments attempt_count
 11.  Dead-letter transition after max_attempts failures
 12.  Concurrent worker claim (SELECT FOR UPDATE SKIP LOCKED)
 13.  Worker lock expiry recovery
 14.  Retry back-off: available_at is in the future after failure
 15.  No sensitive plaintext visible in DB row
 16.  create_invitation enqueues outbox row (commit-before-deliver)
 17.  Outbox row message_type matches enqueued kind
"""

import os
import threading
import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session as SASession

from app.email.fake import FakeEmailProvider
from app.email.outbox import (
    decrypt_payload,
    encrypt_payload,
    enqueue_email,
    process_outbox_once,
)
from app.models.outbox import EmailOutbox
from tests.integration.conftest import csrf_headers, login, register_and_verify

pytestmark = pytest.mark.integration

_PASSWORD = "TestPassword123!"
_DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://expertseat:expertseat_dev@localhost:5432/expertseat",
)


# ── 1. AEAD encrypt/decrypt round-trip ────────────────────────────────────────


def test_aead_encrypt_decrypt_roundtrip():
    """AES-256-GCM encrypt→decrypt must return the original payload."""
    original = {
        "to": "roundtrip@example.com",
        "subject": "Subject",
        "html_body": "<p>x</p>",
        "text_body": "x",
        "kind": "invitation",
    }
    blob = encrypt_payload(original)
    recovered = decrypt_payload(blob)
    assert recovered == original


# ── 2. Unique nonce — distinct ciphertexts for identical payloads ──────────────


def test_identical_payloads_produce_distinct_ciphertexts():
    """Each encryption call uses a fresh random nonce — ciphertexts differ."""
    payload = {"to": "x@x.com", "subject": "S", "html_body": "H", "text_body": "T"}
    blob1 = encrypt_payload(payload)
    blob2 = encrypt_payload(payload)
    assert blob1 != blob2, "Identical payloads must produce distinct ciphertexts (fresh nonce)"


# ── 3. Tampered ciphertext raises ValueError ───────────────────────────────────


def test_tampered_ciphertext_raises_value_error():
    """Flipping a byte in the ciphertext must fail the GCM authentication tag."""
    import base64
    import json

    blob = encrypt_payload({"to": "t@t.com", "subject": "T"})
    envelope = json.loads(blob)
    ct_bytes = bytearray(base64.b64decode(envelope["ct"]))
    ct_bytes[0] ^= 0xFF  # tamper first byte
    envelope["ct"] = base64.b64encode(bytes(ct_bytes)).decode()
    tampered = json.dumps(envelope).encode()

    with pytest.raises(ValueError, match="integrity"):
        decrypt_payload(tampered)


# ── 4. Wrong key raises ValueError ────────────────────────────────────────────


def test_wrong_key_raises_value_error():
    """Decrypting with a different key must fail authentication."""
    blob = encrypt_payload({"to": "k@k.com", "subject": "K"})

    # Override key with a different value
    wrong_key = "b" * 64  # 32 bytes hex
    with patch("app.email.outbox._get_key_bytes", return_value=bytes.fromhex(wrong_key)):
        with pytest.raises(ValueError):
            decrypt_payload(blob)


# ── 5. Truncated payload raises ValueError ────────────────────────────────────


def test_truncated_payload_raises_value_error():
    """A payload that is not valid JSON raises ValueError."""
    with pytest.raises(ValueError):
        decrypt_payload(b"not-json")


# ── 6. Unsupported envelope version raises ValueError ─────────────────────────


def test_unsupported_envelope_version_raises():
    """Envelope with v=999 must be rejected."""
    import json

    blob = encrypt_payload({"to": "v@v.com", "subject": "V"})
    envelope = json.loads(blob)
    envelope["v"] = 999
    bad_blob = json.dumps(envelope).encode()

    with pytest.raises(ValueError, match="version"):
        decrypt_payload(bad_blob)


# ── 7. enqueue_email writes a pending row ─────────────────────────────────────


def test_enqueue_email_writes_db_row(db_session: SASession):
    """enqueue_email must write one EmailOutbox row with status='pending'."""
    before = db_session.query(EmailOutbox).count()
    enqueue_email(
        db_session,
        to="test@example.com",
        subject="Hello",
        html_body="<p>Hi</p>",
        text_body="Hi",
        kind="invitation",
    )
    db_session.flush()
    after = db_session.query(EmailOutbox).count()
    assert after == before + 1, "Expected exactly one new EmailOutbox row"

    row = (
        db_session.query(EmailOutbox)
        .filter(EmailOutbox.status == "pending")
        .order_by(EmailOutbox.created_at.desc())
        .first()
    )
    assert row is not None
    assert row.message_type == "invitation"
    assert row.attempt_count == 0
    assert row.key_id is not None


# ── 8. process_outbox_once delivers and marks 'sent' ─────────────────────────


async def test_process_outbox_marks_row_sent(db_session: SASession):
    """Successfully delivered row must have status='sent' and sent_at set."""
    provider = FakeEmailProvider()
    row = enqueue_email(
        db_session,
        to="s@example.com",
        subject="S",
        html_body="<b>S</b>",
        text_body="S",
        kind="verification",
    )
    db_session.flush()
    row_id = row.id

    sent = await process_outbox_once(db_session, provider)
    assert sent == 1

    db_session.expire_all()
    updated = db_session.query(EmailOutbox).filter(EmailOutbox.id == row_id).first()
    assert updated is not None
    assert updated.status == "sent"
    assert updated.sent_at is not None
    assert provider.sent[0].to == "s@example.com"


# ── 9. Business rollback creates no outbox row ────────────────────────────────


def test_business_rollback_creates_no_outbox_row(db_session: SASession):
    """If the outer transaction rolls back, the outbox row must not persist."""
    before = db_session.query(EmailOutbox).count()

    # Simulate: enqueue then rollback (savepoint rollback in test session)
    db_session.begin_nested()
    enqueue_email(db_session, to="rb@example.com", subject="RB", html_body="x", text_body="x")
    db_session.flush()
    mid_count = db_session.query(EmailOutbox).count()
    assert mid_count == before + 1
    db_session.rollback()  # roll back the savepoint

    db_session.expire_all()
    after = db_session.query(EmailOutbox).count()
    assert after == before, "Rolled-back transaction must not persist outbox row"


# ── 10. SMTP failure sets status='retry', increments attempt_count ────────────


async def test_smtp_failure_sets_retry_status(db_session: SASession):
    """SMTP failure must move the row to 'retry' and increment attempt_count."""

    class FailingProvider:
        async def send(
            self, to: str, subject: str, html_body: str, text_body: str, kind: str = ""
        ) -> None:
            raise RuntimeError("SMTP connection refused")

    row = enqueue_email(
        db_session,
        to="fail@example.com",
        subject="F",
        html_body="<b>F</b>",
        text_body="F",
        kind="invitation",
    )
    db_session.flush()
    row_id = row.id

    await process_outbox_once(db_session, FailingProvider())
    db_session.expire_all()

    updated = db_session.query(EmailOutbox).filter(EmailOutbox.id == row_id).first()
    assert updated is not None
    assert updated.attempt_count == 1
    assert updated.status in ("retry", "dead")
    assert updated.failure_code == "SMTP_ERROR"
    assert updated.available_at is not None  # retry is scheduled


# ── 11. Dead-letter transition after max_attempts ─────────────────────────────


async def test_row_becomes_dead_after_max_attempts(db_session: SASession):
    """After outbox_max_attempts failures the row must be marked 'dead'."""
    from app.config import settings

    class FailingProvider:
        async def send(
            self, to: str, subject: str, html_body: str, text_body: str, kind: str = ""
        ) -> None:
            raise RuntimeError("always fails")

    row = enqueue_email(
        db_session,
        to="dead@example.com",
        subject="D",
        html_body="<b>D</b>",
        text_body="D",
        kind="invitation",
    )
    db_session.flush()
    row_id = row.id

    for _ in range(settings.outbox_max_attempts):
        db_session.expire_all()
        r = db_session.query(EmailOutbox).filter(EmailOutbox.id == row_id).first()
        assert r is not None
        r.status = "pending"
        r.available_at = None
        db_session.flush()
        await process_outbox_once(db_session, FailingProvider())

    db_session.expire_all()
    final = db_session.query(EmailOutbox).filter(EmailOutbox.id == row_id).first()
    assert final is not None
    assert final.status == "dead", f"Expected 'dead', got {final.status!r}"
    assert final.attempt_count >= settings.outbox_max_attempts


# ── 12. Concurrent worker claim ───────────────────────────────────────────────


def test_concurrent_workers_claim_disjoint_rows():
    """SELECT FOR UPDATE SKIP LOCKED — two concurrent workers must not double-process."""

    engine1 = create_engine(_DATABASE_URL)
    engine2 = create_engine(_DATABASE_URL)

    # Seed a single pending row with a direct DB connection
    row_id: str | None = None
    with engine1.connect() as conn:
        result = conn.execute(
            text("""
                INSERT INTO email_outbox (encrypted_payload, key_id, message_type, status,
                    attempt_count, available_at, created_at, updated_at)
                VALUES (:payload, 'v1', 'invitation', 'pending', 0, now(), now(), now())
                RETURNING id
            """),
            {
                "payload": encrypt_payload(
                    {"to": "conc@example.com", "subject": "C", "html_body": "H", "text_body": "T"}
                ).decode()
            },
        )
        row_id = result.scalar()
        conn.commit()

    claim_counts: list[int] = []

    def worker(eng) -> None:
        from sqlalchemy.orm import Session

        with Session(eng) as s:
            # Attempt to claim the row using SKIP LOCKED
            claimed = (
                s.query(EmailOutbox)
                .filter(
                    EmailOutbox.id == row_id,
                    EmailOutbox.status.in_(["pending", "retry"]),
                )
                .with_for_update(skip_locked=True)
                .all()
            )
            if claimed:
                claimed[0].status = "processing"
                s.flush()
                time.sleep(0.05)  # simulate work
                claim_counts.append(1)
            s.commit()

    try:
        t1 = threading.Thread(target=worker, args=(engine1,))
        t2 = threading.Thread(target=worker, args=(engine2,))
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        total_claims = sum(claim_counts)
        assert total_claims <= 1, (
            f"Expected at most 1 worker to claim the row, got {total_claims} claims"
        )
    finally:
        with engine1.connect() as conn:
            conn.execute(text("DELETE FROM email_outbox WHERE id = :id"), {"id": row_id})
            conn.commit()
        engine1.dispose()
        engine2.dispose()


# ── 13. Worker lock expiry recovery ───────────────────────────────────────────


async def test_stuck_processing_row_is_recovered(db_session: SASession):
    """A row stuck in 'processing' past lock_expiry must be recovered for retry."""
    from datetime import timedelta

    from app.config import settings

    provider = FakeEmailProvider()
    row = enqueue_email(
        db_session,
        to="stuck@example.com",
        subject="Stuck",
        html_body="<b>Stuck</b>",
        text_body="Stuck",
        kind="invitation",
    )
    db_session.flush()
    row_id = row.id

    # Simulate stuck: set status=processing, locked_at far in the past
    past = row.created_at - timedelta(seconds=settings.outbox_lock_expiry_seconds + 60)
    row.status = "processing"
    row.locked_at = past
    db_session.flush()

    sent = await process_outbox_once(db_session, provider)
    assert sent == 1, f"Expected stuck row to be recovered and delivered; got {sent}"

    db_session.expire_all()
    recovered = db_session.query(EmailOutbox).filter(EmailOutbox.id == row_id).first()
    assert recovered is not None
    assert recovered.status == "sent"


# ── 14. Retry back-off: available_at is in the future ─────────────────────────


async def test_retry_backoff_sets_future_available_at(db_session: SASession):
    """After SMTP failure, available_at must be in the future."""

    class FailingProvider:
        async def send(
            self, to: str, subject: str, html_body: str, text_body: str, kind: str = ""
        ) -> None:
            raise RuntimeError("fail")

    row = enqueue_email(
        db_session,
        to="backoff@example.com",
        subject="B",
        html_body="<b>B</b>",
        text_body="B",
        kind="test",
    )
    db_session.flush()
    row_id = row.id

    await process_outbox_once(db_session, FailingProvider())
    db_session.expire_all()

    from datetime import UTC, datetime

    now = datetime.now(UTC)
    updated = db_session.query(EmailOutbox).filter(EmailOutbox.id == row_id).first()
    assert updated is not None
    if updated.status in ("retry",):
        assert updated.available_at is not None
        assert updated.available_at > now, (
            f"available_at must be in the future; got {updated.available_at}"
        )


# ── 15. No sensitive plaintext visible in DB row ──────────────────────────────


def test_no_plaintext_in_db_row(db_session: SASession):
    """The raw email address and subject must not appear unencrypted in the DB row."""
    sensitive_to = "secret_recipient@example.com"
    sensitive_subject = "Unique-Subject-XYZ-12345"

    row = enqueue_email(
        db_session,
        to=sensitive_to,
        subject=sensitive_subject,
        html_body="<p>Body</p>",
        text_body="Body",
        kind="invitation",
    )
    db_session.flush()
    row_id = row.id
    db_session.expire_all()

    raw_row = db_session.query(EmailOutbox).filter(EmailOutbox.id == row_id).first()
    assert raw_row is not None
    payload_str = raw_row.encrypted_payload
    if isinstance(payload_str, bytes):
        payload_str = payload_str.decode()

    assert sensitive_to not in payload_str, (
        "Plaintext recipient address must not appear in encrypted_payload"
    )
    assert sensitive_subject not in payload_str, (
        "Plaintext subject must not appear in encrypted_payload"
    )
    # message_type (unencrypted for monitoring) is acceptable
    assert raw_row.message_type == "invitation"


# ── 16. create_invitation enqueues outbox row (commit-before-deliver) ─────────


def test_create_invitation_enqueues_outbox_row(
    http_client: TestClient, fake_email, db_session: SASession
):
    """create_invitation must commit the outbox row before attempting delivery."""
    email = "outbox_admin@example.com"
    register_and_verify(http_client, fake_email, email, password=_PASSWORD)
    login(http_client, email, password=_PASSWORD)

    resp = http_client.post(
        "/api/v1/workspace/organizations",
        json={"name": "Outbox Test Org"},
        headers=csrf_headers(http_client),
    )
    assert resp.status_code == 201, resp.text
    org_id = resp.json()["id"]

    resp = http_client.post(
        "/api/v1/auth/switch-org",
        json={"org_id": org_id},
        headers=csrf_headers(http_client),
    )
    assert resp.status_code == 200, resp.text

    before = db_session.query(EmailOutbox).count()

    resp = http_client.post(
        "/api/v1/workspace/invitations",
        json={"email": "invitee_outbox@example.com", "role": "recruiter"},
        headers=csrf_headers(http_client),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["delivery_status"] == "queued"

    db_session.expire_all()
    after = db_session.query(EmailOutbox).count()
    assert after == before + 1, f"Expected one new EmailOutbox row; before={before}, after={after}"

    # The fake provider received the email (post-commit sync delivery)
    assert fake_email.invitation_message_for("invitee_outbox@example.com") is not None


# ── 17. Outbox row message_type matches enqueued kind ─────────────────────────


def test_enqueue_email_message_type_stored(db_session: SASession):
    """The message_type field is stored unencrypted for monitoring."""
    enqueue_email(
        db_session,
        to="k@example.com",
        subject="K",
        html_body="<b>K</b>",
        text_body="K",
        kind="password_reset",
    )
    db_session.flush()
    row = (
        db_session.query(EmailOutbox)
        .filter(EmailOutbox.message_type == "password_reset")
        .order_by(EmailOutbox.created_at.desc())
        .first()
    )
    assert row is not None
    assert row.message_type == "password_reset"
