"""Add immutable supplier invoice records and three-way match status.

Revision ID: 0034_supplier_invoice_matching
Revises: 0033_expenses_ledger
"""
from alembic import op
import sqlalchemy as sa


revision = "0034_supplier_invoice_matching"
down_revision = "0033_expenses_ledger"
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
    "'purchase_order_receipt_recorded', 'supplier_invoice_recorded', "
    "'expense_created', 'expense_voided')"
)

PREVIOUS_AUDIT_EVENTS = AUDIT_EVENTS.replace("'supplier_invoice_recorded', ", "")


def upgrade():
    op.create_table(
        "supplier_invoices",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("purchase_order_id", sa.Uuid(), nullable=False),
        sa.Column("supplier_id", sa.Uuid(), nullable=False),
        sa.Column("invoice_reference", sa.String(length=120), nullable=False),
        sa.Column("invoice_date", sa.Date(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("subtotal", sa.Numeric(14, 2), nullable=False),
        sa.Column("tax_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("total_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("match_status", sa.String(length=24), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "match_status IN ('matched', 'pending_receipt', 'disputed')",
            name="supplier_invoice_match_status_supported",
        ),
        sa.CheckConstraint("length(trim(invoice_reference)) > 0",
                           name="supplier_invoice_reference_not_empty"),
        sa.CheckConstraint("length(currency) = 3 AND currency = upper(currency)",
                           name="supplier_invoice_currency_iso"),
        sa.CheckConstraint("subtotal >= 0 AND tax_amount >= 0 AND total_amount >= 0",
                           name="supplier_invoice_amounts_nonnegative"),
        sa.ForeignKeyConstraint(
            ["company_id", "purchase_order_id"],
            ["purchase_orders.company_id", "purchase_orders.id"],
            name="fk_supplier_invoices_order_same_company", ondelete="NO ACTION",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "supplier_id"],
            ["suppliers.company_id", "suppliers.id"],
            name="fk_supplier_invoices_supplier_same_company", ondelete="NO ACTION",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "created_by_user_id"],
            ["company_memberships.company_id", "company_memberships.user_id"],
            name="fk_supplier_invoices_creator_membership", ondelete="NO ACTION",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"], ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "id", name="uq_supplier_invoices_company_id"),
        sa.UniqueConstraint(
            "company_id", "supplier_id", "invoice_reference",
            name="uq_supplier_invoice_reference",
        ),
    )
    op.create_index(
        "ix_supplier_invoices_company_order", "supplier_invoices",
        ["company_id", "purchase_order_id"],
    )
    op.create_table(
        "supplier_invoice_lines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("invoice_id", sa.Uuid(), nullable=False),
        sa.Column("purchase_order_line_id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.Numeric(12, 3), nullable=False),
        sa.Column("unit_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("line_total", sa.Numeric(14, 2), nullable=False),
        sa.CheckConstraint("quantity > 0", name="supplier_invoice_line_quantity_positive"),
        sa.CheckConstraint(
            "unit_price >= 0 AND line_total >= 0",
            name="supplier_invoice_line_amounts_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "invoice_id"],
            ["supplier_invoices.company_id", "supplier_invoices.id"],
            name="fk_supplier_invoice_lines_invoice_same_company", ondelete="NO ACTION",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "purchase_order_line_id"],
            ["purchase_order_lines.company_id", "purchase_order_lines.id"],
            name="fk_supplier_invoice_lines_order_line_same_company", ondelete="NO ACTION",
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "id", name="uq_supplier_invoice_lines_company_id"),
        sa.UniqueConstraint(
            "company_id", "invoice_id", "purchase_order_line_id",
            name="uq_supplier_invoice_line_order_line",
        ),
    )
    op.create_index(
        "ix_supplier_invoice_lines_company_invoice", "supplier_invoice_lines",
        ["company_id", "invoice_id"],
    )
    for table in ("supplier_invoices", "supplier_invoice_lines"):
        op.execute(f"REVOKE ALL ON {table} FROM sales_dash_app")
        op.execute(f"GRANT SELECT, INSERT ON {table} TO sales_dash_app")
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY {table}_company_access ON {table}
            FOR ALL TO sales_dash_app
            USING (
                company_id =
                    NULLIF(current_setting('app.current_company_id', true), '')::uuid
            )
            WITH CHECK (
                company_id =
                    NULLIF(current_setting('app.current_company_id', true), '')::uuid
            )
        """)
    op.drop_constraint("event_type_is_supported", "audit_logs", type_="check")
    op.create_check_constraint("event_type_is_supported", "audit_logs", AUDIT_EVENTS)


def downgrade():
    op.drop_constraint("event_type_is_supported", "audit_logs", type_="check")
    op.create_check_constraint(
        "event_type_is_supported", "audit_logs", PREVIOUS_AUDIT_EVENTS
    )
    for table in ("supplier_invoice_lines", "supplier_invoices"):
        op.execute(f"DROP POLICY IF EXISTS {table}_company_access ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
        op.execute(f"REVOKE SELECT, INSERT ON {table} FROM sales_dash_app")
    op.drop_index("ix_supplier_invoice_lines_company_invoice",
                  table_name="supplier_invoice_lines")
    op.drop_table("supplier_invoice_lines")
    op.drop_index("ix_supplier_invoices_company_order", table_name="supplier_invoices")
    op.drop_table("supplier_invoices")
