"""Add delivery tracking columns to organization_invitations.

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-14

Adds three columns to track email delivery state for invitations.
A failed delivery leaves the invitation in 'failed' status so an admin
can resend without creating a duplicate.
"""

import sqlalchemy as sa

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organization_invitations",
        sa.Column(
            "delivery_status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
    )
    op.add_column(
        "organization_invitations",
        sa.Column("delivery_attempted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "organization_invitations",
        sa.Column("delivery_failure_code", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("organization_invitations", "delivery_failure_code")
    op.drop_column("organization_invitations", "delivery_attempted_at")
    op.drop_column("organization_invitations", "delivery_status")
