"""Add user_consents table for versioned terms and privacy notice acceptance.

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-14

Append-only table recording each user's acceptance of terms of service and
privacy notice with the exact version accepted at the time.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_consents",
        sa.Column(
            "id", UUID(as_uuid=False), nullable=False, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column("user_id", UUID(as_uuid=False), nullable=False),
        sa.Column("terms_version", sa.String(50), nullable=True),
        sa.Column("privacy_notice_version", sa.String(50), nullable=True),
        sa.Column("org_id", UUID(as_uuid=False), nullable=True),
        sa.Column("request_id", sa.String(), nullable=True),
        sa.Column(
            "accepted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_consents_user_id", "user_consents", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_user_consents_user_id", table_name="user_consents")
    op.drop_table("user_consents")
