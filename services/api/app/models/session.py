from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.organization import Membership, Organization
    from app.models.user import User


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, server_default=func.gen_random_uuid()
    )
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    org_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True,
    )
    membership_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("memberships.id", ondelete="SET NULL"),
        nullable=True,
    )
    refresh_token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    family_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False, index=True)
    ip_address_hash: Mapped[str] = mapped_column(Text, nullable=False)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    user: Mapped[User] = relationship("User", back_populates="auth_sessions")
    organization: Mapped[Organization] = relationship("Organization")
    membership: Mapped[Membership] = relationship("Membership")
