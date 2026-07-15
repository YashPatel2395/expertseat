"""Make auth_sessions.org_id and membership_id nullable

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-13

Nullable org context on auth_sessions supports valid states where a user has no
active workspace membership at login time:
  - A user whose memberships were all disabled or removed
  - An existing invited user before they have selected a workspace
  - A deliberately supported no-active-workspace authentication state

NULL means "no active workspace context" — never a placeholder UUID.
GET /auth/me returns org_id="" and role="" for these sessions.
Workspace-scoped endpoints return 403 NO_ACTIVE_WORKSPACE.

Downgrade policy: null-context sessions are ephemeral authentication state.
Deleting them before restoring the NOT NULL constraint is safe — the affected
users must re-authenticate, at which point a valid (non-null) session is created
if they have an active membership, or a new null-context session otherwise.
If a null-context user downgrade is unwanted in a specific deployment, the
recommendation is to re-upgrade immediately rather than run in the 0002 state.
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
    # Downgrade policy: delete null-context sessions before restoring NOT NULL.
    # Sessions are ephemeral — affected users re-authenticate on next request.
    # This is safe because null-context sessions represent "no active workspace",
    # not lost data; the user's account and memberships are unaffected.
    op.execute("DELETE FROM auth_sessions WHERE org_id IS NULL OR membership_id IS NULL")

    op.drop_constraint("auth_sessions_org_id_fkey", "auth_sessions", type_="foreignkey")
    op.drop_constraint("auth_sessions_membership_id_fkey", "auth_sessions", type_="foreignkey")

    # Restore NOT NULL (safe because NULLs were deleted above)
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
