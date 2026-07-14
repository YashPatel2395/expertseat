"""Unit tests verifying ORM ForeignKey declarations match the migration schema.

These tests inspect the SQLAlchemy Column metadata without hitting the database,
proving that ForeignKey constraints are declared and configured correctly in the
ORM layer.  They guard against accidental removal of FK declarations that would
break relationship loading and DB-level referential integrity.

Tested invariants:
  1. EmailVerificationToken.user_id has CASCADE FK to users.id
  2. PasswordResetToken.user_id has CASCADE FK to users.id
  3. AuthSession.org_id has SET NULL FK to organizations.id (nullable)
  4. AuthSession.membership_id has SET NULL FK to memberships.id (nullable)
  5. AuthSession.user_id has CASCADE FK to users.id (non-nullable)
  6. Membership.user_id has CASCADE FK to users.id
  7. Membership.org_id has CASCADE FK to organizations.id
"""


from app.models.organization import Membership
from app.models.session import AuthSession
from app.models.user import EmailVerificationToken, PasswordResetToken


def _fk_for(model, col_name: str):
    """Return the first ForeignKey on *col_name* of *model*'s mapped table."""
    col = model.__table__.c[col_name]
    fks = list(col.foreign_keys)
    assert fks, f"{model.__name__}.{col_name} has no ForeignKey declaration"
    return fks[0]


# ── 1 & 2: token models have user FK ──────────────────────────────────────────


def test_email_verification_token_user_id_fk_to_users():
    fk = _fk_for(EmailVerificationToken, "user_id")
    assert fk.column.table.name == "users"
    assert fk.ondelete == "CASCADE"


def test_password_reset_token_user_id_fk_to_users():
    fk = _fk_for(PasswordResetToken, "user_id")
    assert fk.column.table.name == "users"
    assert fk.ondelete == "CASCADE"


# ── 3 & 4: auth_sessions nullable org/membership FKs ─────────────────────────


def test_auth_session_org_id_nullable_fk_with_set_null():
    col = AuthSession.__table__.c["org_id"]
    assert col.nullable, "org_id must be nullable to support no-org sessions"
    fk = _fk_for(AuthSession, "org_id")
    assert fk.column.table.name == "organizations"
    assert fk.ondelete == "SET NULL"


def test_auth_session_membership_id_nullable_fk_with_set_null():
    col = AuthSession.__table__.c["membership_id"]
    assert col.nullable, "membership_id must be nullable to support no-org sessions"
    fk = _fk_for(AuthSession, "membership_id")
    assert fk.column.table.name == "memberships"
    assert fk.ondelete == "SET NULL"


# ── 5: auth_sessions user FK is non-nullable ──────────────────────────────────


def test_auth_session_user_id_nonnullable_fk_with_cascade():
    col = AuthSession.__table__.c["user_id"]
    assert not col.nullable, "user_id must not be nullable"
    fk = _fk_for(AuthSession, "user_id")
    assert fk.column.table.name == "users"
    assert fk.ondelete == "CASCADE"


# ── 6 & 7: membership FKs ─────────────────────────────────────────────────────


def test_membership_user_id_fk_to_users():
    fk = _fk_for(Membership, "user_id")
    assert fk.column.table.name == "users"
    assert fk.ondelete == "CASCADE"


def test_membership_org_id_fk_to_organizations():
    fk = _fk_for(Membership, "org_id")
    assert fk.column.table.name == "organizations"
    assert fk.ondelete == "CASCADE"
