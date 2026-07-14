"""Add target_type and request_id to audit_events; drop ip_hash.

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-14
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("audit_events", sa.Column("target_type", sa.Text(), nullable=True))
    op.add_column(
        "audit_events",
        sa.Column("request_id", postgresql.UUID(as_uuid=False), nullable=True),
    )
    op.drop_column("audit_events", "ip_hash")


def downgrade() -> None:
    op.drop_column("audit_events", "request_id")
    op.drop_column("audit_events", "target_type")
    op.add_column("audit_events", sa.Column("ip_hash", sa.Text(), nullable=True))
