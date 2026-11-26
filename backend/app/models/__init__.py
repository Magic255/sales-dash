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
from .sales_target import SalesTarget  # noqa: F401 - register monthly target model


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
        CheckConstraint(
            "salesperson_discount_limit >= 0 AND salesperson_discount_limit <= 100",
            name="salesperson_discount_limit_range",
        ),
        CheckConstraint(
            "manager_discount_limit >= 0 AND manager_discount_limit <= 100",
            name="manager_discount_limit_range",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    salesperson_discount_limit: Mapped[Decimal] = mapped_column(
        db.Numeric(5, 2), nullable=False,
        default=Decimal("5.00"), server_default="5.00",
    )
    manager_discount_limit: Mapped[Decimal] = mapped_column(
        db.Numeric(5, 2), nullable=False,
        default=Decimal("15.00"), server_default="15.00",
    )
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
            "'mfa_recovery_code_used', 'company_settings_updated', "
            "'team_member_role_changed', 'team_member_suspended', "
            "'team_member_reactivated', 'product_created', 'product_updated', "
            "'discount_limits_updated', 'discount_approval_requested', "
            "'discount_approval_decided', 'price_floor_override', 'discount_applied')",
            name="event_type_is_supported",
        ),
        db.Index("ix_audit_logs_company_time", "company_id", "occurred_at"),
        db.Index("ix_audit_logs_actor_time", "actor_user_id", "occurred_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    actor_user_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    company_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    details: Mapped[dict | None] = mapped_column(db.JSON, nullable=True)
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
        CheckConstraint("cost_price >= 0", name="cost_price_nonnegative"),
        CheckConstraint("minimum_selling_price >= cost_price", name="minimum_price_covers_cost"),
        CheckConstraint("unit_price >= minimum_selling_price", name="unit_price_covers_floor"),
        CheckConstraint("reorder_level >= 0", name="reorder_level_nonnegative"),
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
    cost_price: Mapped[Decimal] = mapped_column(
        db.Numeric(12, 2), nullable=False, default=0, server_default="0"
    )
    minimum_selling_price: Mapped[Decimal] = mapped_column(
        db.Numeric(12, 2), nullable=False, default=0, server_default="0"
    )
    track_inventory: Mapped[bool] = mapped_column(
        nullable=False, default=False, server_default="false"
    )
    reorder_level: Mapped[Decimal] = mapped_column(
        db.Numeric(12, 3), nullable=False, default=0, server_default="0"
    )
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


class ProductBatch(db.Model):
    """A product lot with an optional best-before or expiry date."""

    __tablename__ = "product_batches"
    __table_args__ = (
        db.UniqueConstraint("company_id", "id", name="uq_product_batches_company_id_id"),
        db.UniqueConstraint(
            "company_id", "product_id", "batch_code",
            name="uq_product_batches_company_product_code",
        ),
        db.ForeignKeyConstraint(
            ["company_id", "product_id"],
            ["products.company_id", "products.id"],
            ondelete="NO ACTION",
            name="fk_product_batches_product_same_company",
        ),
        db.ForeignKeyConstraint(
            ["company_id", "created_by_user_id"],
            ["company_memberships.company_id", "company_memberships.user_id"],
            ondelete="NO ACTION",
            name="fk_product_batches_creator_membership",
        ),
        CheckConstraint("length(trim(batch_code)) > 0", name="batch_code_not_empty"),
        db.Index("ix_product_batches_company_product", "company_id", "product_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    batch_code: Mapped[str] = mapped_column(String(80), nullable=False)
    expiry_date: Mapped[date | None] = mapped_column(db.Date)
    created_by_user_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class StockMovement(db.Model):
    """Append-only quantity and reservation movement for a product batch."""

    __tablename__ = "stock_movements"
    __table_args__ = (
        db.UniqueConstraint("company_id", "id", name="uq_stock_movements_company_id_id"),
        db.ForeignKeyConstraint(
            ["company_id", "product_id"],
            ["products.company_id", "products.id"],
            ondelete="NO ACTION",
            name="fk_stock_movements_product_same_company",
        ),
        db.ForeignKeyConstraint(
            ["company_id", "batch_id"],
            ["product_batches.company_id", "product_batches.id"],
            ondelete="NO ACTION",
            name="fk_stock_movements_batch_same_company",
        ),
        db.ForeignKeyConstraint(
            ["company_id", "actor_user_id"],
            ["company_memberships.company_id", "company_memberships.user_id"],
            ondelete="NO ACTION",
            name="fk_stock_movements_actor_same_company",
        ),
        db.ForeignKeyConstraint(
            ["company_id", "sale_id"],
            ["sales.company_id", "sales.id"],
            ondelete="NO ACTION",
            name="fk_stock_movements_sale_same_company",
        ),
        CheckConstraint(
            "movement_type IN ('received', 'sold', 'returned', 'damaged', "
            "'adjusted', 'reserved', 'released')",
            name="stock_movement_type_supported",
        ),
        CheckConstraint(
            "quantity_delta <> 0 OR reserved_delta <> 0",
            name="stock_movement_nonzero",
        ),
        CheckConstraint(
            "length(trim(reason)) > 0", name="stock_movement_reason_not_empty"
        ),
        CheckConstraint(
            "(movement_type IN ('received', 'returned') AND quantity_delta > 0 "
            "AND reserved_delta = 0) OR "
            "(movement_type IN ('sold', 'damaged') AND quantity_delta < 0 "
            "AND reserved_delta = 0) OR "
            "(movement_type = 'adjusted' AND quantity_delta <> 0 "
            "AND reserved_delta = 0) OR "
            "(movement_type = 'reserved' AND quantity_delta = 0 "
            "AND reserved_delta > 0) OR "
            "(movement_type = 'released' AND quantity_delta = 0 "
            "AND reserved_delta < 0)",
            name="stock_movement_delta_matches_type",
        ),
        db.Index("ix_stock_movements_company_batch", "company_id", "batch_id"),
        db.Index("ix_stock_movements_company_product", "company_id", "product_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    batch_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    sale_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    actor_user_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    movement_type: Mapped[str] = mapped_column(String(20), nullable=False)
    quantity_delta: Mapped[Decimal] = mapped_column(
        db.Numeric(12, 3), nullable=False, default=0, server_default="0"
    )
    reserved_delta: Mapped[Decimal] = mapped_column(
        db.Numeric(12, 3), nullable=False, default=0, server_default="0"
    )
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
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


class DiscountApprovalRequest(db.Model):
    """Decision history for a sale discount above its role limit."""

    __tablename__ = "discount_approval_requests"
    __table_args__ = (
        db.ForeignKeyConstraint(
            ["company_id", "sale_id"], ["sales.company_id", "sales.id"],
            ondelete="CASCADE", name="fk_discount_approval_sale_same_company",
        ),
        db.ForeignKeyConstraint(
            ["company_id", "requested_by_user_id"],
            ["company_memberships.company_id", "company_memberships.user_id"],
            ondelete="NO ACTION", name="fk_discount_approval_requester_membership",
        ),
        db.ForeignKeyConstraint(
            ["company_id", "approver_user_id"],
            ["company_memberships.company_id", "company_memberships.user_id"],
            ondelete="NO ACTION", name="fk_discount_approval_approver_membership",
        ),
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'superseded')",
            name="status_is_supported",
        ),
        CheckConstraint(
            "requested_discount_percent > 0 AND requested_discount_percent <= 100",
            name="discount_percent_range",
        ),
        CheckConstraint("length(trim(reason)) > 0", name="reason_not_empty"),
        db.Index("ix_discount_approvals_company_status", "company_id", "status", "created_at"),
        db.Index("ix_discount_approvals_sale_created", "company_id", "sale_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
    )
    sale_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    requested_by_user_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    approver_user_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending"
    )
    requested_discount_percent: Mapped[Decimal] = mapped_column(db.Numeric(5, 2), nullable=False)
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    decision_reason: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


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
        db.ForeignKeyConstraint(
            ["company_id", "batch_id"],
            ["product_batches.company_id", "product_batches.id"],
            ondelete="NO ACTION",
            name="fk_sale_items_batch_same_company",
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
    batch_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    line_total: Mapped[Decimal] = mapped_column(db.Numeric(14, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
