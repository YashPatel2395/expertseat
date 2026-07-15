"""Add email_outbox table for transactional email delivery.

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-14

Transactional outbox: invitation (and other) emails are written to this table
in the same DB transaction as the triggering business event.  A background
worker reads pending rows, decrypts the AES-256-GCM payload, and delivers
via SMTP.  SMTP failure produces a retryable row — not an HTTP error — which
eliminates the enumeration surface exposed by synchronous delivery-status
feedback.

Status state machine:
  pending → processing → sent
                      → retry  (SMTP failure, within max_attempts)
                      → dead   (SMTP failure, max_attempts exhausted)

Encryption:
  encrypted_payload stores a JSON envelope:
    {"v":1,"alg":"AES-256-GCM","kid":"<key-id>",
     "nonce":"<base64-12-bytes>","ct":"<base64-ciphertext+tag>"}
  Key management: OUTBOX_ENCRYPTION_KEY env var (hex-encoded 32 bytes).
  See ADR-007 for full cryptographic design.

Downgrade behavior:
  DROP TABLE email_outbox — all pending outbox records are lost.
  In production, process the queue to empty before downgrading.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "email_outbox",
        sa.Column(
            "id",
            UUID(as_uuid=False),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        # AES-256-GCM JSON envelope (see ADR-007).  Never expose in APIs or logs.
        sa.Column("encrypted_payload", sa.Text, nullable=False),
        sa.Column("key_id", sa.String(50), nullable=False, server_default="v1"),
        sa.Column("message_type", sa.String(50), nullable=False, server_default="email"),
        # Status: pending | processing | sent | retry | dead
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("attempt_count", sa.Integer, nullable=False, server_default="0"),
        # When the row becomes eligible for worker pickup (None = immediately)
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=True),
        # Worker-claim fields for SELECT FOR UPDATE SKIP LOCKED semantics
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(50), nullable=True),
        # Safe failure category — no raw SMTP errors or recipient addresses
        sa.Column("failure_code", sa.String(100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    # Primary worker pickup index — covers the SELECT FOR UPDATE SKIP LOCKED query
    op.create_index(
        "ix_email_outbox_pickup",
        "email_outbox",
        ["status", "available_at"],
        postgresql_where=sa.text("status IN ('pending', 'processing', 'retry')"),
    )

    # Monitoring index — quickly count rows by status
    op.create_index("ix_email_outbox_status", "email_outbox", ["status"])


def downgrade() -> None:
    # WARNING: this drops ALL pending outbox records.
    # In production: drain the queue before downgrading.
    op.drop_index("ix_email_outbox_status", table_name="email_outbox")
    op.drop_index("ix_email_outbox_pickup", table_name="email_outbox")
    op.drop_table("email_outbox")
