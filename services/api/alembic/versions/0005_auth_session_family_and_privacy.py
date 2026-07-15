"""Add absolute family lifetime and remove ip_address_hash from auth_sessions.

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-14

Changes:
  - auth_sessions: add family_created_at, family_expires_at (absolute TTL)
  - auth_sessions: drop ip_address_hash (permanent IP storage removed)
  - auth_sessions: rename user_agent → user_agent_summary, truncate to 200 chars

Policy: family_expires_at = family_created_at + 14 days. Rotation never extends
family_expires_at. Existing rows get family_created_at = created_at and
family_expires_at = created_at + INTERVAL '14 days'.
"""

import sqlalchemy as sa

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add family_created_at with server default (existing rows get current timestamp initially)
    op.add_column(
        "auth_sessions",
        sa.Column(
            "family_created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    # Backfill family_created_at from created_at for existing rows
    op.execute("UPDATE auth_sessions SET family_created_at = created_at")

    # Add family_expires_at (14 days from family_created_at)
    op.add_column(
        "auth_sessions",
        sa.Column(
            "family_expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now() + INTERVAL '14 days'"),
        ),
    )
    # Backfill family_expires_at for existing rows
    op.execute(
        "UPDATE auth_sessions SET family_expires_at = family_created_at + INTERVAL '14 days'"
    )

    # Remove ip_address_hash (permanent IP-derived storage)
    op.drop_column("auth_sessions", "ip_address_hash")

    # Rename user_agent → user_agent_summary and truncate to 200 chars
    op.alter_column("auth_sessions", "user_agent", new_column_name="user_agent_summary")
    op.execute(
        "UPDATE auth_sessions "
        "SET user_agent_summary = LEFT(user_agent_summary, 200) "
        "WHERE user_agent_summary IS NOT NULL AND LENGTH(user_agent_summary) > 200"
    )


def downgrade() -> None:
    op.alter_column("auth_sessions", "user_agent_summary", new_column_name="user_agent")
    op.add_column(
        "auth_sessions",
        sa.Column("ip_address_hash", sa.Text(), nullable=False, server_default=sa.text("''")),
    )
    op.drop_column("auth_sessions", "family_expires_at")
    op.drop_column("auth_sessions", "family_created_at")
