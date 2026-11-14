"""Core identity and multi-company membership models."""

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from ..company_invitation import CompanyInvitation  # noqa: F401
from ..email_verification import EmailVerificationToken  # noqa: F401
from ..extensions import db
from ..mfa_models import MfaCredential, MfaRecoveryCode  # noqa: F401
from ..password_reset import PasswordResetToken  # noqa: F401


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


class User(db.Model):
    """A global account that can belong to multiple companies."""

    __tablename__ = "users"
    __table_args__ = (
        db.UniqueConstraint("email", name="uq_users_email"),
        CheckConstraint(
            "length(email) > 0 AND email = lower(trim(email))",
            name="email_normalized",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(120))
    password_hash: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True, server_default="true")
    email_verified: Mapped[bool] = mapped_column(
        nullable=False, default=False, server_default="false"
    )
    auth_version: Mapped[int] = mapped_column(nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=utc_now
    )

    @validates("email")
    def normalize_email(self, _key: str, value: str) -> str:
        return value.strip().lower()

    memberships: Mapped[list["CompanyMembership"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Company(db.Model):
    """A tenant workspace with its own company-specific data."""

    __tablename__ = "companies"
    __table_args__ = (
        db.UniqueConstraint("slug", name="uq_companies_slug"),
        CheckConstraint("length(trim(name)) > 0", name="name_not_empty"),
        CheckConstraint("length(slug) > 0", name="slug_not_empty"),
        CheckConstraint("slug = lower(trim(slug))", name="slug_normalized"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=utc_now
    )

    @validates("slug")
    def normalize_slug(self, _key: str, value: str) -> str:
        return value.strip().lower()

    memberships: Mapped[list["CompanyMembership"]] = relationship(
        back_populates="company", cascade="all, delete-orphan"
    )


class CompanyMembership(db.Model):
    """A user's membership and role inside one company."""

    __tablename__ = "company_memberships"
    __table_args__ = (
        CheckConstraint(
            "role IN ('admin', 'manager', 'salesperson', 'viewer')",
            name="role_is_supported",
        ),
        CheckConstraint(
            "status IN ('active', 'invited', 'suspended')",
            name="status_is_supported",
        ),
        db.Index("ix_company_memberships_user_id", "user_id"),
    )

    company_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(
        String(20), nullable=False, default="viewer", server_default="viewer"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", server_default="active"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    company: Mapped[Company] = relationship(back_populates="memberships")
    user: Mapped[User] = relationship(back_populates="memberships")


class AuditLog(db.Model):
    """Minimal security events, scoped by company and never edited by the app."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        db.CheckConstraint(
            "event_type IN ('login_succeeded', 'password_changed', "
            "'company_selected', 'logout', 'email_verified', 'password_reset', "
            "'company_invitation_created', 'company_invitation_accepted', "
            "'company_invitation_revoked', 'mfa_enabled', 'mfa_disabled', "
            "'mfa_recovery_code_used')",
            name="event_type_is_supported",
        ),
        db.Index("ix_audit_logs_company_time", "company_id", "occurred_at"),
        db.Index("ix_audit_logs_actor_time", "actor_user_id", "occurred_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    actor_user_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    company_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Customer(db.Model):
    """A customer record owned by exactly one company."""

    __tablename__ = "customers"
    __table_args__ = (
        db.UniqueConstraint("company_id", "id", name="uq_customers_company_id_id"),
        db.UniqueConstraint("company_id", "email", name="uq_customers_company_email"),
        db.ForeignKeyConstraint(
            ["company_id", "created_by_user_id"],
            ["company_memberships.company_id", "company_memberships.user_id"],
            ondelete="NO ACTION",
            name="fk_customers_creator_membership",
        ),
        CheckConstraint("length(trim(name)) > 0", name="name_not_empty"),
        CheckConstraint(
            "email IS NULL OR email = lower(trim(email))",
            name="email_normalized",
        ),
        db.Index("ix_customers_company_name", "company_id", "name"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(40))
    organization: Mapped[str | None] = mapped_column(String(160))
    notes: Mapped[str | None] = mapped_column(String(2000))
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True, server_default="true")
    created_by_user_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=utc_now
    )


class Product(db.Model):
    """A company-owned product or service offered for sale."""

    __tablename__ = "products"
    __table_args__ = (
        db.UniqueConstraint("company_id", "id", name="uq_products_company_id_id"),
        db.UniqueConstraint("company_id", "sku", name="uq_products_company_sku"),
        db.ForeignKeyConstraint(
            ["company_id", "created_by_user_id"],
            ["company_memberships.company_id", "company_memberships.user_id"],
            ondelete="NO ACTION",
            name="fk_products_creator_membership",
        ),
        CheckConstraint("length(trim(name)) > 0", name="name_not_empty"),
        CheckConstraint("length(trim(sku)) > 0", name="sku_not_empty"),
        CheckConstraint("unit_price >= 0", name="unit_price_nonnegative"),
        CheckConstraint(
            "currency = upper(currency) AND length(currency) = 3",
            name="currency_iso_code",
        ),
        db.Index("ix_products_company_name", "company_id", "name"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    sku: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(String(2000))
    unit_price: Mapped[Decimal] = mapped_column(db.Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="TZS", server_default="TZS"
    )
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True, server_default="true")
    created_by_user_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=utc_now
    )


class Sale(db.Model):
    """A company-scoped sales transaction."""

    __tablename__ = "sales"
    __table_args__ = (
        db.UniqueConstraint("company_id", "id", name="uq_sales_company_id_id"),
        db.UniqueConstraint("company_id", "sale_number", name="uq_sales_company_sale_number"),
        db.ForeignKeyConstraint(
            ["company_id", "customer_id"],
            ["customers.company_id", "customers.id"],
            ondelete="NO ACTION",
            name="fk_sales_customer_same_company",
        ),
        db.ForeignKeyConstraint(
            ["company_id", "salesperson_user_id"],
            ["company_memberships.company_id", "company_memberships.user_id"],
            ondelete="NO ACTION",
            name="fk_sales_salesperson_membership",
        ),
        db.ForeignKeyConstraint(
            ["company_id", "created_by_user_id"],
            ["company_memberships.company_id", "company_memberships.user_id"],
            ondelete="NO ACTION",
            name="fk_sales_creator_membership",
        ),
        CheckConstraint("length(trim(sale_number)) > 0", name="sale_number_not_empty"),
        CheckConstraint(
            "status IN ('draft', 'completed', 'void')",
            name="status_is_supported",
        ),
        CheckConstraint(
            "length(currency) = 3 AND currency = upper(currency)",
            name="currency_iso_code",
        ),
        CheckConstraint("subtotal >= 0", name="subtotal_nonnegative"),
        CheckConstraint("discount_amount >= 0", name="discount_nonnegative"),
        CheckConstraint("tax_amount >= 0", name="tax_nonnegative"),
        CheckConstraint("total_amount >= 0", name="total_nonnegative"),
        db.Index("ix_sales_company_date", "company_id", "sale_date"),
        db.Index("ix_sales_company_customer", "company_id", "customer_id"),
        db.Index("ix_sales_company_salesperson", "company_id", "salesperson_user_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    sale_number: Mapped[str] = mapped_column(String(40), nullable=False)
    customer_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    salesperson_user_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    created_by_user_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", server_default="draft"
    )
    sale_date: Mapped[date] = mapped_column(db.Date, nullable=False)
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="TZS", server_default="TZS"
    )
    subtotal: Mapped[Decimal] = mapped_column(
        db.Numeric(14, 2), nullable=False, default=0, server_default="0"
    )
    discount_amount: Mapped[Decimal] = mapped_column(
        db.Numeric(14, 2), nullable=False, default=0, server_default="0"
    )
    tax_amount: Mapped[Decimal] = mapped_column(
        db.Numeric(14, 2), nullable=False, default=0, server_default="0"
    )
    total_amount: Mapped[Decimal] = mapped_column(
        db.Numeric(14, 2), nullable=False, default=0, server_default="0"
    )
    notes: Mapped[str | None] = mapped_column(String(2000))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=utc_now
    )


class SaleItem(db.Model):
    """A line item with immutable product details captured at sale time."""

    __tablename__ = "sale_items"
    __table_args__ = (
        db.ForeignKeyConstraint(
            ["company_id", "sale_id"],
            ["sales.company_id", "sales.id"],
            ondelete="CASCADE",
            name="fk_sale_items_sale_same_company",
        ),
        db.ForeignKeyConstraint(
            ["company_id", "product_id"],
            ["products.company_id", "products.id"],
            ondelete="NO ACTION",
            name="fk_sale_items_product_same_company",
        ),
        CheckConstraint("length(trim(product_name)) > 0", name="product_name_not_empty"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_price >= 0", name="unit_price_nonnegative"),
        CheckConstraint("discount_amount >= 0", name="discount_nonnegative"),
        CheckConstraint("line_total >= 0", name="line_total_nonnegative"),
        db.Index("ix_sale_items_company_sale", "company_id", "sale_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    sale_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    product_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    product_name: Mapped[str] = mapped_column(String(160), nullable=False)
    sku_snapshot: Mapped[str] = mapped_column(String(64), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(db.Numeric(12, 3), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(db.Numeric(12, 2), nullable=False)
    discount_amount: Mapped[Decimal] = mapped_column(
        db.Numeric(14, 2), nullable=False, default=0, server_default="0"
    )
    line_total: Mapped[Decimal] = mapped_column(db.Numeric(14, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

