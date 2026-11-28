"""Add tenant-scoped expense ledger and audit events.

Revision ID: 0033_expenses_ledger
Revises: 0032_batch_serial_ref
"""

# ruff: noqa: I001
from alembic import op
import sqlalchemy as sa


revision = "0033_expenses_ledger"
down_revision = "0032_batch_serial_ref"
branch_labels = None
depends_on = None


AUDIT_EVENTS = (
    "event_type IN ('login_succeeded', 'password_changed', 'company_selected', 'logout', "
    "'email_verified', 'password_reset', 'company_invitation_created', "
    "'company_invitation_accepted', 'company_invitation_revoked', 'mfa_enabled', "
    "'mfa_disabled', 'mfa_recovery_code_used', 'company_settings_updated', "
    "'team_member_role_changed', 'team_member_suspended', 'team_member_reactivated', "
    "'product_created', 'product_updated', 'discount_limits_updated', "
    "'discount_approval_requested', 'discount_approval_decided', 'price_floor_override', "
    "'discount_applied', 'product_compliance_verified', 'product_compliance_rejected', "
    "'product_compliance_recalled', 'product_compliance_exception', "
    "'product_compliance_policy_updated', 'product_compliance_not_required_release', "
    "'product_compliance_evidence_uploaded', 'product_compliance_evidence_downloaded', "
    "'supplier_created', 'supplier_approved', 'supplier_restricted', 'supplier_suspended', "
    "'supplier_rejected', 'supplier_re_review_required', 'supplier_document_uploaded', "
    "'supplier_document_rejected', 'supplier_document_downloaded', 'purchase_order_created', "
    "'purchase_order_receipt_recorded', 'expense_created', 'expense_voided')"
)


def upgrade():
    op.create_table(
        "expenses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("category", sa.String(length=60), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("expense_date", sa.Date(), nullable=False),
        sa.Column("payment_method", sa.String(length=40), nullable=True),
        sa.Column("reference", sa.String(length=120), nullable=True),
        sa.Column("notes", sa.String(length=1000), nullable=True),
        sa.Column("status", sa.String(length=12), server_default="recorded", nullable=False),
        sa.Column("void_reason", sa.String(length=500), nullable=True),
        sa.Column("voided_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("voided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("amount > 0", name="expense_amount_positive"),
        sa.CheckConstraint("length(trim(description)) > 0", name="expense_description_not_empty"),
        sa.CheckConstraint("length(trim(category)) > 0", name="expense_category_not_empty"),
        sa.CheckConstraint("currency = upper(currency) AND length(currency) = 3", name="expense_currency_iso"),
        sa.CheckConstraint("status IN ('recorded', 'void')", name="expense_status_supported"),
        sa.CheckConstraint(
            "(status = 'recorded' AND void_reason IS NULL AND voided_by_user_id IS NULL AND voided_at IS NULL) "
            "OR (status = 'void' AND length(trim(void_reason)) > 0 AND voided_by_user_id IS NOT NULL AND voided_at IS NOT NULL)",
            name="expense_void_fields_consistent",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "created_by_user_id"],
            ["company_memberships.company_id", "company_memberships.user_id"],
            name="fk_expenses_creator_membership",
            ondelete="NO ACTION",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "voided_by_user_id"],
            ["company_memberships.company_id", "company_memberships.user_id"],
            name="fk_expenses_voider_membership",
            ondelete="NO ACTION",
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "id", name="uq_expenses_company_id"),
    )
    op.create_index("ix_expenses_company_date", "expenses", ["company_id", "expense_date"])
    op.create_index("ix_expenses_company_category", "expenses", ["company_id", "category"])
    op.execute("REVOKE ALL ON expenses FROM sales_dash_app")
    op.execute("GRANT SELECT, INSERT ON expenses TO sales_dash_app")
    op.execute(
        "GRANT UPDATE (status, void_reason, voided_by_user_id, voided_at) "
        "ON expenses TO sales_dash_app"
    )
    op.execute("ALTER TABLE expenses ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE expenses FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY expenses_company_access ON expenses
        FOR ALL TO sales_dash_app
        USING (
            company_id =
                NULLIF(current_setting('app.current_company_id', true), '')::uuid
        )
        WITH CHECK (
            company_id =
                NULLIF(current_setting('app.current_company_id', true), '')::uuid
        )
        """
    )
    op.drop_constraint("event_type_is_supported", "audit_logs", type_="check")
    op.create_check_constraint("event_type_is_supported", "audit_logs", AUDIT_EVENTS)


def downgrade():
    op.drop_constraint("event_type_is_supported", "audit_logs", type_="check")
    op.create_check_constraint(
        "event_type_is_supported",
        "audit_logs",
        "event_type IN ('login_succeeded', 'password_changed', 'company_selected', 'logout', "
        "'email_verified', 'password_reset', 'company_invitation_created', "
        "'company_invitation_accepted', 'company_invitation_revoked', 'mfa_enabled', "
        "'mfa_disabled', 'mfa_recovery_code_used', 'company_settings_updated', "
        "'team_member_role_changed', 'team_member_suspended', 'team_member_reactivated', "
        "'product_created', 'product_updated', 'discount_limits_updated', "
        "'discount_approval_requested', 'discount_approval_decided', 'price_floor_override', "
        "'discount_applied', 'product_compliance_verified', 'product_compliance_rejected', "
        "'product_compliance_recalled', 'product_compliance_exception', "
        "'product_compliance_policy_updated', 'product_compliance_not_required_release', "
        "'product_compliance_evidence_uploaded', 'product_compliance_evidence_downloaded', "
        "'supplier_created', 'supplier_approved', 'supplier_restricted', 'supplier_suspended', "
        "'supplier_rejected', 'supplier_re_review_required', 'supplier_document_uploaded', "
        "'supplier_document_rejected', 'supplier_document_downloaded', 'purchase_order_created', "
        "'purchase_order_receipt_recorded')",
    )
    op.execute("DROP POLICY IF EXISTS expenses_company_access ON expenses")
    op.execute("ALTER TABLE expenses NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE expenses DISABLE ROW LEVEL SECURITY")
    op.execute("REVOKE SELECT, INSERT, UPDATE ON expenses FROM sales_dash_app")
    op.drop_index("ix_expenses_company_category", table_name="expenses")
    op.drop_index("ix_expenses_company_date", table_name="expenses")
    op.drop_table("expenses")
