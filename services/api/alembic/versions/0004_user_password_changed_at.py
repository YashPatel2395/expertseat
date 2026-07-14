"""Add users.password_changed_at for audit and session invalidation

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-13

Tracks when a user last changed their password. Used by the auth service
to update the field on password reset and change-password operations.
Nullable on existing rows (NULL = never explicitly changed via API).
"""

import sqlalchemy as sa

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "password_changed_at")
