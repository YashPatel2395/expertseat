"""Make auth_sessions.org_id and membership_id nullable

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-13

A new user who has just registered but not yet created an org must still
receive a valid auth session after login.  The previous NOT NULL constraint
on org_id / membership_id forced a placeholder UUID into those columns —
which violated the FK constraints.  Making them nullable is the correct
representation of the "no org yet" state.
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop the old NOT NULL + CASCADE FK constraints on auth_sessions
    op.drop_constraint("auth_sessions_org_id_fkey", "auth_sessions", type_="foreignkey")
    op.drop_constraint("auth_sessions_membership_id_fkey", "auth_sessions", type_="foreignkey")

    # Make columns nullable
    op.alter_column("auth_sessions", "org_id", nullable=True)
    op.alter_column("auth_sessions", "membership_id", nullable=True)

    # Re-add FK constraints with SET NULL so that deleting an org/membership
    # preserves the session row (the user just loses org context).
    op.create_foreign_key(
        "auth_sessions_org_id_fkey",
        "auth_sessions",
        "organizations",
        ["org_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "auth_sessions_membership_id_fkey",
        "auth_sessions",
        "memberships",
        ["membership_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("auth_sessions_org_id_fkey", "auth_sessions", type_="foreignkey")
    op.drop_constraint("auth_sessions_membership_id_fkey", "auth_sessions", type_="foreignkey")

    # Restore NOT NULL (this will fail if any NULL values exist)
    op.alter_column("auth_sessions", "org_id", nullable=False)
    op.alter_column("auth_sessions", "membership_id", nullable=False)

    op.create_foreign_key(
        "auth_sessions_org_id_fkey",
        "auth_sessions",
        "organizations",
        ["org_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "auth_sessions_membership_id_fkey",
        "auth_sessions",
        "memberships",
        ["membership_id"],
        ["id"],
        ondelete="CASCADE",
    )
