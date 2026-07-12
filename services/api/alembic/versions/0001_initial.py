"""Initial migration

Revision ID: 0001
Revises:
Create Date: 2026-07-12
"""

from alembic import op  # noqa: F401

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Foundation migration — no tables yet.
    # Entity groups (Organization, User, Blueprint, Candidate, Interview, Report)
    # are planned but not yet implemented. See ARCHITECTURE.md.
    pass


def downgrade() -> None:
    pass
