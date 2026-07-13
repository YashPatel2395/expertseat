# Import all models so that Alembic's autogenerate can discover them via Base.metadata.
# The order matters: tables with no foreign keys first.
from app.models.audit import AuditEvent  # noqa: F401
from app.models.organization import Membership, Organization, OrganizationInvitation  # noqa: F401
from app.models.session import AuthSession  # noqa: F401
from app.models.user import EmailVerificationToken, PasswordResetToken, User  # noqa: F401
