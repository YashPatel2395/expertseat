"""Transactional email outbox: enqueue, encrypt, and process email rows.

Encryption uses AES-256-GCM as provided by the PyCA `cryptography` library
(version >=43.0.0, pinned to 49.0.0 in pyproject.toml).

See ADR-007 for the full cryptographic design rationale.

Encrypted envelope stored in `email_outbox.encrypted_payload` (UTF-8 JSON):

    {
      "v": 1,                          // envelope format version
      "alg": "AES-256-GCM",           // algorithm identifier
      "kid": "<key-id>",              // key slot for rotation
      "nonce": "<base64url-12-bytes>",
      "ct": "<base64url-ciphertext+16-byte-GCM-tag>"
    }

Workflow (sync-first + outbox-retry):
  1. Route handler: enqueue_email() writes row + business records in ONE transaction.
  2. Route handler commits.
  3. AFTER commit: attempt_delivery_after_commit() opens a NEW session and calls
     deliver_now().  This provides low-latency delivery in the common case while
     the committed row guarantees durability.
  4. A background worker calls process_outbox_once() for retry/dead-letter
     handling using SELECT FOR UPDATE SKIP LOCKED to prevent double-processing.

Transaction boundary invariant:
  No email is ever attempted before the outbox row is committed.
"""

from __future__ import annotations

import base64
import json
import os
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import structlog
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.outbox import EmailOutbox

if TYPE_CHECKING:
    from app.email.base import EmailProvider

logger = structlog.get_logger()

_GCM_NONCE_BYTES = 12
_GCM_KEY_BYTES = 32  # AES-256
_ENVELOPE_VERSION = 1
_ALG = "AES-256-GCM"

# Categorised, non-sensitive failure codes stored in outbox rows.
# These must not contain raw exception messages or recipient data.
_FAILURE_CODE_DECRYPT = "DECRYPT_ERROR"
_FAILURE_CODE_SMTP = "SMTP_ERROR"
_FAILURE_CODE_INVALID = "INVALID_PAYLOAD"


# ── Key management ────────────────────────────────────────────────────────────


def _get_key_bytes(kid: str) -> bytes:
    """Resolve *kid* to the corresponding 32-byte AES key.

    Currently only the active key is supported.  Key rotation support
    (resolving historical key IDs) is reserved for a future migration.
    See ADR-007 — Rotation Procedure.
    """
    from app.config import settings

    active_kid = settings.outbox_active_key_id
    if kid != active_kid:
        raise ValueError(
            f"Unsupported key ID '{kid}' — only '{active_kid}' is configured. "
            "Pending records encrypted with an old key must be processed before "
            "the old key is removed."
        )
    raw_hex = settings.outbox_encryption_key
    try:
        key_bytes = bytes.fromhex(raw_hex)
    except ValueError as exc:
        raise ValueError("OUTBOX_ENCRYPTION_KEY must be a hex string") from exc
    if len(key_bytes) != _GCM_KEY_BYTES:
        raise ValueError(
            f"OUTBOX_ENCRYPTION_KEY must be {_GCM_KEY_BYTES} bytes; got {len(key_bytes)}"
        )
    return key_bytes


# ── AEAD encrypt / decrypt ────────────────────────────────────────────────────


def encrypt_payload(payload: dict) -> bytes:
    """Encrypt *payload* dict with AES-256-GCM.

    Returns UTF-8 JSON bytes representing the versioned envelope.
    Each call uses a fresh random 96-bit nonce — identical payloads
    produce distinct ciphertexts.
    """
    from app.config import settings

    kid = settings.outbox_active_key_id
    key_bytes = _get_key_bytes(kid)
    aesgcm = AESGCM(key_bytes)
    nonce = os.urandom(_GCM_NONCE_BYTES)
    plaintext = json.dumps(payload, separators=(",", ":")).encode()
    # encrypt() returns ciphertext + 16-byte GCM authentication tag
    ciphertext_tag = aesgcm.encrypt(nonce, plaintext, None)
    envelope = {
        "v": _ENVELOPE_VERSION,
        "alg": _ALG,
        "kid": kid,
        "nonce": base64.b64encode(nonce).decode(),
        "ct": base64.b64encode(ciphertext_tag).decode(),
    }
    return json.dumps(envelope, separators=(",", ":")).encode()


def decrypt_payload(blob: str | bytes) -> dict:
    """Decrypt *blob* (envelope JSON string or bytes).

    Raises ValueError for:
    - Truncated or malformed envelope
    - Unsupported envelope version or algorithm
    - Unknown key ID
    - Authentication tag failure (tampered or wrong key)
    """
    try:
        envelope = json.loads(blob)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"Malformed outbox envelope: {exc}") from exc

    if not isinstance(envelope, dict):
        raise ValueError("Outbox envelope must be a JSON object")

    version = envelope.get("v")
    if version != _ENVELOPE_VERSION:
        raise ValueError(f"Unsupported envelope version: {version!r}")

    alg = envelope.get("alg")
    if alg != _ALG:
        raise ValueError(f"Unsupported algorithm: {alg!r}")

    kid = envelope.get("kid")
    if not isinstance(kid, str):
        raise ValueError("Envelope missing 'kid'")

    try:
        nonce = base64.b64decode(envelope["nonce"])
        ciphertext_tag = base64.b64decode(envelope["ct"])
    except (KeyError, Exception) as exc:
        raise ValueError(f"Invalid envelope fields: {exc}") from exc

    if len(nonce) != _GCM_NONCE_BYTES:
        raise ValueError(f"Nonce must be {_GCM_NONCE_BYTES} bytes; got {len(nonce)}")

    if len(ciphertext_tag) < 16:
        raise ValueError("Ciphertext too short (missing authentication tag)")

    key_bytes = _get_key_bytes(kid)
    aesgcm = AESGCM(key_bytes)
    try:
        plaintext = aesgcm.decrypt(nonce, ciphertext_tag, None)
    except InvalidTag as exc:
        raise ValueError("Outbox payload integrity check failed") from exc

    return json.loads(plaintext)


# ── Public API — enqueue ──────────────────────────────────────────────────────


def enqueue_email(
    db: Session,
    *,
    to: str,
    subject: str,
    html_body: str,
    text_body: str,
    kind: str = "",
) -> EmailOutbox:
    """Write an encrypted outbox row in the current (uncommitted) transaction.

    IMPORTANT: This function adds the row to the session but does NOT commit.
    The caller MUST commit after this call, together with any business records
    (invitation row, etc.), to achieve the transactional outbox guarantee.

    After commit, call attempt_delivery_after_commit() for immediate delivery.
    """
    from app.config import settings

    payload = {
        "to": to,
        "subject": subject,
        "html_body": html_body,
        "text_body": text_body,
        "kind": kind,
    }
    blob = encrypt_payload(payload).decode()  # Text column expects str
    now = datetime.now(UTC)
    row = EmailOutbox(
        encrypted_payload=blob,
        message_type=kind or "email",
        key_id=settings.outbox_active_key_id,
        status="pending",
        attempt_count=0,
        available_at=now,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    return row


# ── Delivery ──────────────────────────────────────────────────────────────────


async def deliver_now(db: Session, row: EmailOutbox, provider: EmailProvider) -> bool:
    """Attempt delivery of *row* that is already committed.

    This is called from a NEW session after the business transaction commits.

    On success: marks the row 'sent'.
    On failure: increments attempt_count, moves to 'retry' or 'dead'.
    Returns True if delivery succeeded.

    Failure codes stored are safe identifiers — no raw exception message,
    no recipient address.
    """
    from app.config import settings

    try:
        payload = decrypt_payload(row.encrypted_payload)
    except ValueError:
        logger.error(
            "outbox_decrypt_failed",
            outbox_id=row.id,
            key_id=row.key_id,
        )
        row.status = "dead"
        row.failure_code = _FAILURE_CODE_DECRYPT
        row.updated_at = datetime.now(UTC)
        return False

    try:
        await provider.send(
            to=payload["to"],
            subject=payload["subject"],
            html_body=payload["html_body"],
            text_body=payload["text_body"],
            kind=payload.get("kind", ""),
        )
        now = datetime.now(UTC)
        row.status = "sent"
        row.sent_at = now
        row.updated_at = now
        logger.info("outbox_delivered", outbox_id=row.id, message_type=row.message_type)
        return True
    except Exception:
        now = datetime.now(UTC)
        row.attempt_count += 1
        row.failure_code = _FAILURE_CODE_SMTP
        row.updated_at = now
        if row.attempt_count >= settings.outbox_max_attempts:
            row.status = "dead"
            logger.warning(
                "outbox_dead",
                outbox_id=row.id,
                message_type=row.message_type,
                attempt_count=row.attempt_count,
            )
        else:
            import random

            jitter = random.uniform(0.8, 1.2)
            backoff_seconds = int(30 * (2 ** (row.attempt_count - 1)) * jitter)
            row.status = "retry"
            row.available_at = now + timedelta(seconds=backoff_seconds)
            logger.info(
                "outbox_retry_scheduled",
                outbox_id=row.id,
                message_type=row.message_type,
                attempt_count=row.attempt_count,
                backoff_seconds=backoff_seconds,
            )
        return False


async def attempt_delivery_after_commit(
    row_id: str,
    provider: EmailProvider,
    db: Session | None = None,
) -> None:
    """Attempt delivery of the already-committed outbox row.

    Two modes:
    - ``db`` provided (route handler): use the caller's session directly and
      do NOT commit internally.  The caller must commit after this call to
      persist the delivery status update.  This works with test infrastructure
      that uses savepoint-based transaction isolation, where a new ``SessionLocal``
      session would not see rows committed only to a savepoint.
    - ``db`` is None (background worker): open a new ``SessionLocal`` session
      and commit internally.

    In both cases delivery is attempted only if the row exists and is still
    ``pending`` — concurrent workers that already claimed the row are skipped.
    """
    if db is not None:
        row = db.get(EmailOutbox, row_id)
        if row is None or row.status != "pending":
            return
        row.status = "processing"
        row.locked_at = datetime.now(UTC)
        db.flush()
        success = await deliver_now(db, row, provider)
        if not success and row.status == "processing":
            row.status = "retry"
            row.available_at = datetime.now(UTC) + timedelta(minutes=1)
        db.flush()
        return

    from app.database import SessionLocal

    with SessionLocal() as delivery_db:
        row = delivery_db.get(EmailOutbox, row_id)
        if row is None or row.status != "pending":
            return
        row.status = "processing"
        row.locked_at = datetime.now(UTC)
        delivery_db.flush()
        success = await deliver_now(delivery_db, row, provider)
        if not success and row.status == "processing":
            row.status = "retry"
            row.available_at = datetime.now(UTC) + timedelta(minutes=1)
        delivery_db.commit()


# ── Worker — concurrency-safe batch processor ─────────────────────────────────


async def process_outbox_once(db: Session, provider: EmailProvider, *, limit: int = 50) -> int:
    """Claim and deliver up to *limit* available outbox rows.

    Uses SELECT FOR UPDATE SKIP LOCKED so concurrent workers claim disjoint
    sets of rows without blocking each other.  Claimed rows move to 'processing'
    state; the status is persisted before delivery so a worker crash leaves the
    row in 'processing' for recovery.

    Lock recovery: rows stuck in 'processing' beyond outbox_lock_expiry_seconds
    are treated as available for retry on the next call.

    Returns the number of rows successfully delivered.
    """
    from app.config import settings

    now = datetime.now(UTC)
    lock_expiry_cutoff = now - timedelta(seconds=settings.outbox_lock_expiry_seconds)

    # Claim rows: pending/retry with available_at <= now, OR stuck processing
    rows = (
        db.query(EmailOutbox)
        .filter(
            or_(
                # Normal pending / retry rows
                (EmailOutbox.status.in_(["pending", "retry"]))
                & (EmailOutbox.available_at.is_(None) | (EmailOutbox.available_at <= now)),
                # Recover rows stuck in 'processing' past lock expiry
                (EmailOutbox.status == "processing")
                & (EmailOutbox.locked_at <= lock_expiry_cutoff),
            )
        )
        .with_for_update(skip_locked=True)
        .limit(limit)
        .all()
    )

    if not rows:
        return 0

    # Atomically mark all claimed rows as 'processing'
    worker_id = os.urandom(8).hex()
    for row in rows:
        row.status = "processing"
        row.locked_at = now
        row.locked_by = worker_id
    db.flush()

    sent_count = 0
    for row in rows:
        success = await deliver_now(db, row, provider)
        if success:
            sent_count += 1

    db.flush()
    return sent_count
