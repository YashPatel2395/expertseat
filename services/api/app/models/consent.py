"""UserConsent model — append-only record of terms and privacy notice acceptance.

Design decisions:
  - Append-only: records are never updated or deleted. Each acceptance creates a row.
  - Versioned: terms_version and privacy_notice_version are captured at acceptance time.
  - Tied to invitation acceptance for new users: consent is required at account creation.
  - org_id is nullable: initial consent happens before org context is established.
  - request_id links to the HTTP request for audit trail correlation.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class UserConsent(Base):
    """Append-only record of a user's acceptance of terms and/or privacy notice."""

    __tablename__ = "user_consents"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, server_default=func.gen_random_uuid()
    )
    user_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    # Which version of the terms was accepted (e.g. "2026-07-01")
    terms_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Which version of the privacy notice was accepted
    privacy_notice_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Org context at the time of acceptance (may be None for pre-org flows)
    org_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), nullable=True)
    # Correlates with the HTTP request that produced this consent record
    request_id: Mapped[str | None] = mapped_column(String, nullable=True)
    accepted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
