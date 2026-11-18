"""Monthly company and salesperson sales targets."""

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, Date, ForeignKey, Numeric, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from ..extensions import db


class SalesTarget(db.Model):
    """A monthly revenue target for a company or one salesperson."""

    __tablename__ = "sales_targets"
    __table_args__ = (
        db.UniqueConstraint(
            "company_id", "period_start", "target_type",
            "salesperson_user_id", "currency",
            name="uq_sales_targets_period_owner_currency",
        ),
        db.ForeignKeyConstraint(
            ["company_id", "salesperson_user_id"],
            ["company_memberships.company_id", "company_memberships.user_id"],
            ondelete="CASCADE",
            name="fk_sales_targets_salesperson_membership",
        ),
        CheckConstraint(
            "target_type IN ('company', 'salesperson')",
            name="target_type_supported",
        ),
        CheckConstraint(
            "(target_type = 'company' AND salesperson_user_id IS NULL) OR "
            "(target_type = 'salesperson' AND salesperson_user_id IS NOT NULL)",
            name="target_owner_matches_type",
        ),
        CheckConstraint("target_amount > 0", name="target_amount_positive"),
        CheckConstraint(
            "length(currency) = 3 AND currency = upper(currency)",
            name="currency_iso_code",
        ),
        db.Index("ix_sales_targets_company_period", "company_id", "period_start"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    target_type: Mapped[str] = mapped_column(String(20), nullable=False)
    salesperson_user_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    target_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
