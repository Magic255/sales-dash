"""Encrypted per-account MFA credentials and one-time recovery codes."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from .extensions import db


class MfaCredential(db.Model):
    """An account's encrypted TOTP secret; enabled_at is null during setup."""

    __tablename__ = "mfa_credentials"

    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    secret_ciphertext: Mapped[str] = mapped_column(String(255), nullable=False)
    enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MfaRecoveryCode(db.Model):
    """A single-use, hashed recovery code belonging to one global account."""

    __tablename__ = "mfa_recovery_codes"
    __table_args__ = (
        db.UniqueConstraint("user_id", "code_hash", name="uq_mfa_recovery_user_hash"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
