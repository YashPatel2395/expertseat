"""SQLAlchemy model for the transactional email outbox.

Rows are written atomically with the triggering DB transaction (e.g., invitation
creation). A background worker reads pending rows, decrypts the payload, and
delivers via the configured email provider. On SMTP failure the row is retried
with bounded exponential backoff before being marked 'dead'.

Payload encryption: AES-256-GCM via the `cryptography` library.
See ADR-007 and app.email.outbox for details.

Status state machine:
  pending → processing → sent
                      → retry → processing (retry)
                      → dead (max attempts)

Concurrency: workers use SELECT FOR UPDATE SKIP LOCKED on (status, available_at)
to claim disjoint rows.  The locked_at / locked_by fields enable lock-expiry
recovery for crashed workers.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


class EmailOutbox(Base):
    __tablename__ = "email_outbox"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, server_default=func.gen_random_uuid()
    )
    # Encrypted envelope (AES-256-GCM JSON blob).  See app.email.outbox.encrypt_payload.
    # Never expose this column in API responses or logs.
    # Stored as UTF-8 JSON text; encrypted_payload is a str at the Python layer
    # because SQLAlchemy's Text column always returns str regardless of what was stored.
    encrypted_payload: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    # Which key slot encrypted this row.  Supports key rotation.
    key_id: Mapped[str] = mapped_column(String(50), nullable=False, default="v1")
    # Unencrypted message type for monitoring without decryption.
    # Values: "invitation", "verification", "password_reset", "email"
    message_type: Mapped[str] = mapped_column(String(50), nullable=False, default="email")
    # Status state machine: pending → processing → sent | retry → dead
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # When this row becomes eligible for pickup.  None = immediately.
    available_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Set when a worker claims the row; cleared (implicitly) on state transition.
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Short worker identifier for diagnostics.  Not sensitive.
    locked_by: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Safe failure category — no raw exception messages, no recipient addresses.
    failure_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        # Primary worker pickup index
        Index(
            "ix_email_outbox_pickup",
            "status",
            "available_at",
            postgresql_where=(
                # Only index rows that workers need to process
                # (PostgreSQL partial index syntax handled via DDL in migration)
            ),
        ),
    )
