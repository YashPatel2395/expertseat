"""Transactional email outbox: enqueue, encrypt, and process email rows.

Encryption uses AES-256-GCM as provided by the PyCA `cryptography` library
(version pinned to 49.0.0 in pyproject.toml).

See ADR-007 for the full cryptographic design rationale.

Envelope versions:

  v1 (legacy, no AAD):
    {
      "v": 1,
      "alg": "AES-256-GCM",
      "kid": "<key-id>",
      "nonce": "<base64url-12-bytes>",
      "ct": "<base64url-ciphertext+16-byte-GCM-tag>"
    }

  v2 (current, with AAD):
    Same JSON structure but also includes "msg_type" in the envelope.
    AAD = canonical JSON of {"alg":..., "kid":..., "msg_type":..., "v":2}
    (sorted keys, no spaces).

Key rotation:
  OUTBOX_ENCRYPTION_KEYS=v1:<hex32>,v2:<hex32>  (preferred, keyring format)
  OUTBOX_ENCRYPTION_KEY=<hex32>                  (legacy single-key, still supported)
  outbox_active_key_id identifies which key is used for new encryptions.

Workflow (Tx A / network / Tx B):
  1. Route handler: enqueue_email() writes row + business records in ONE transaction.
  2. Route handler commits.
  3. AFTER commit: attempt_delivery_after_commit() runs two separate transactions:
       Tx A  — claim the row (SELECT FOR UPDATE SKIP LOCKED, set processing, commit)
       Net   — decrypt payload + SMTP (no DB lock held)
       Tx B  — finalize: re-fetch by (id, locked_by), mark sent/retry/dead, commit
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
_ENVELOPE_VERSION = 2
_LEGACY_VERSION = 1
_ALG = "AES-256-GCM"

# Categorised, non-sensitive failure codes stored in outbox rows.
_FAILURE_CODE_DECRYPT = "DECRYPT_ERROR"
_FAILURE_CODE_SMTP = "SMTP_ERROR"
_FAILURE_CODE_INVALID = "INVALID_PAYLOAD"


# ── Key management ────────────────────────────────────────────────────────────


def _build_keyring() -> dict[str, bytes]:
    """Build a mapping of key-id → raw key bytes from settings.

    Prefers OUTBOX_ENCRYPTION_KEYS (keyring format: 'v1:<hex>,v2:<hex>').
    Falls back to OUTBOX_ENCRYPTION_KEY (legacy single-key).
    """
    from app.config import settings

    keyring: dict[str, bytes] = {}

    if settings.outbox_encryption_keys:
        for entry in settings.outbox_encryption_keys.split(","):
            kid, _, hex_key = entry.strip().partition(":")
            if not kid or not hex_key:
                raise ValueError(f"Invalid OUTBOX_ENCRYPTION_KEYS entry: {entry!r}")
            try:
                key_bytes = bytes.fromhex(hex_key)
            except ValueError as exc:
                raise ValueError(f"OUTBOX_ENCRYPTION_KEYS key '{kid}' is not valid hex") from exc
            if len(key_bytes) != _GCM_KEY_BYTES:
                raise ValueError(
                    f"OUTBOX_ENCRYPTION_KEYS key '{kid}' must be {_GCM_KEY_BYTES} bytes; "
                    f"got {len(key_bytes)}"
                )
            keyring[kid] = key_bytes
    elif settings.outbox_encryption_key:
        raw_hex = settings.outbox_encryption_key
        try:
            key_bytes = bytes.fromhex(raw_hex)
        except ValueError as exc:
            raise ValueError("OUTBOX_ENCRYPTION_KEY must be a hex string") from exc
        if len(key_bytes) != _GCM_KEY_BYTES:
            raise ValueError(
                f"OUTBOX_ENCRYPTION_KEY must be {_GCM_KEY_BYTES} bytes; got {len(key_bytes)}"
            )
        keyring[settings.outbox_active_key_id] = key_bytes

    if not keyring:
        raise ValueError(
            "No outbox encryption key configured. "
            "Set OUTBOX_ENCRYPTION_KEYS (e.g. 'v1:<hex>') or OUTBOX_ENCRYPTION_KEY."
        )

    return keyring


def _get_key_bytes(kid: str) -> bytes:
    """Resolve *kid* to the corresponding 32-byte AES key via the keyring."""
    keyring = _build_keyring()
    if kid not in keyring:
        raise ValueError(
            f"Unknown key ID '{kid}'. "
            "Configure it in OUTBOX_ENCRYPTION_KEYS or OUTBOX_ENCRYPTION_KEY."
        )
    return keyring[kid]


# ── AEAD encrypt / decrypt ────────────────────────────────────────────────────


def encrypt_payload(payload: dict, message_type: str = "") -> bytes:
    """Encrypt *payload* dict with AES-256-GCM (v2 envelope with AAD).

    Returns UTF-8 JSON bytes representing the versioned envelope.
    Each call uses a fresh random 96-bit nonce — identical payloads
    produce distinct ciphertexts.

    The Associated Authenticated Data (AAD) authenticates the envelope
    header fields, preventing an attacker from swapping metadata between
    messages while keeping the ciphertext valid.
    """
    from app.config import settings

    kid = settings.outbox_active_key_id
    key_bytes = _get_key_bytes(kid)
    aesgcm = AESGCM(key_bytes)
    nonce = os.urandom(_GCM_NONCE_BYTES)
    plaintext = json.dumps(payload, separators=(",", ":")).encode()

    # AAD authenticates the envelope metadata (v2+)
    aad_dict = {"alg": _ALG, "kid": kid, "msg_type": message_type, "v": _ENVELOPE_VERSION}
    aad = json.dumps(aad_dict, sort_keys=True, separators=(",", ":")).encode()

    ciphertext_tag = aesgcm.encrypt(nonce, plaintext, aad)
    envelope = {
        "v": _ENVELOPE_VERSION,
        "alg": _ALG,
        "kid": kid,
        "msg_type": message_type,
        "nonce": base64.b64encode(nonce).decode(),
        "ct": base64.b64encode(ciphertext_tag).decode(),
    }
    return json.dumps(envelope, separators=(",", ":")).encode()


def decrypt_payload(blob: str | bytes) -> dict:
    """Decrypt *blob* (envelope JSON string or bytes).

    Handles both v1 envelopes (no AAD) and v2 envelopes (with AAD).

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
    if version not in (_LEGACY_VERSION, _ENVELOPE_VERSION):
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

    # v1: no AAD; v2+: reconstruct AAD from envelope fields
    if version == _LEGACY_VERSION:
        aad: bytes | None = None
    else:
        msg_type = envelope.get("msg_type", "")
        aad_dict = {"alg": _ALG, "kid": kid, "msg_type": msg_type, "v": version}
        aad = json.dumps(aad_dict, sort_keys=True, separators=(",", ":")).encode()

    try:
        plaintext = aesgcm.decrypt(nonce, ciphertext_tag, aad)
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
    blob = encrypt_payload(payload, message_type=kind or "email").decode()
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
    """Attempt delivery of *row* using the current session.

    On success: marks the row 'sent'.
    On failure: increments attempt_count, moves to 'retry' or 'dead'.
    Returns True if delivery succeeded.
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
) -> None:
    """Attempt delivery of the already-committed outbox row.

    Uses the Tx A / network / Tx B pattern:
      Tx A   — open a new session, SELECT FOR UPDATE SKIP LOCKED to claim the
               pending row (set status=processing, locked_by=worker_id), commit.
      Network — decrypt payload, call SMTP provider (no DB lock held).
      Tx B   — open a new session, re-fetch by (id, locked_by), finalize
               (sent/retry/dead), commit.

    This ensures no lock is held during the SMTP call and stale-worker
    recovery is possible via the locked_by identifier.
    """
    from app.database import SessionLocal

    worker_id = os.urandom(8).hex()

    # Tx A: claim
    with SessionLocal() as db_a:
        row = (
            db_a.query(EmailOutbox)
            .filter(EmailOutbox.id == row_id, EmailOutbox.status == "pending")
            .with_for_update(skip_locked=True)
            .first()
        )
        if row is None:
            return  # already claimed or delivered by a concurrent worker
        row.status = "processing"
        row.locked_at = datetime.now(UTC)
        row.locked_by = worker_id
        db_a.commit()

    # Network + Tx B: deliver and finalize
    with SessionLocal() as db_b:
        row = (
            db_b.query(EmailOutbox)
            .filter(
                EmailOutbox.id == row_id,
                EmailOutbox.locked_by == worker_id,
                EmailOutbox.status == "processing",
            )
            .first()
        )
        if row is None:
            return
        await deliver_now(db_b, row, provider)
        db_b.commit()


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

    rows = (
        db.query(EmailOutbox)
        .filter(
            or_(
                (EmailOutbox.status.in_(["pending", "retry"]))
                & (EmailOutbox.available_at.is_(None) | (EmailOutbox.available_at <= now)),
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
