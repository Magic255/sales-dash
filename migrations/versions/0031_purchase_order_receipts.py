"""Add company-scoped purchase orders and partial receipt matching.

Revision ID: 0031_purchase_order_receipts
Revises: 0030_supplier_documents_receipt_gate
"""

# ruff: noqa: I001
from alembic import op
import sqlalchemy as sa


revision = "0031_purchase_order_receipts"
down_revision = "0030_supplier_documents_receipt_gate"
branch_labels = None
depends_on = None


def _tenant_table(table):
    op.execute(f"REVOKE ALL ON {table} FROM sales_dash_app")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON {table} TO sales_dash_app")
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"""
        CREATE POLICY {table}_company_access ON {table}
        FOR ALL TO sales_dash_app
        USING (company_id = NULLIF(current_setting('app.current_company_id', true), '')::uuid)
        WITH CHECK (company_id = NULLIF(current_setting('app.current_company_id', true), '')::uuid)
    """)


def upgrade():
    op.create_table(
        "purchase_orders",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("supplier_id", sa.Uuid(), nullable=False),
        sa.Column("order_number", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=24), server_default="issued", nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("notes", sa.String(length=1000), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "id", name="uq_purchase_orders_company_id"),
        sa.UniqueConstraint("company_id", "order_number", name="uq_purchase_orders_number"),
        sa.ForeignKeyConstraint(
            ["company_id", "supplier_id"], ["suppliers.company_id", "suppliers.id"],
            ondelete="NO ACTION", name="fk_purchase_orders_supplier_same_company",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "created_by_user_id"],
            ["company_memberships.company_id", "company_memberships.user_id"],
            ondelete="NO ACTION", name="fk_purchase_orders_creator_membership",
        ),
        sa.CheckConstraint("status IN ('issued', 'partially_received', 'received', 'cancelled')",
                           name="purchase_order_status_supported"),
        sa.CheckConstraint(
            "length(trim(order_number)) > 0", name="purchase_order_number_not_empty"
        ),
        sa.CheckConstraint("length(currency) = 3 AND currency = upper(currency)",
                           name="purchase_order_currency_iso"),
    )
    op.create_index("ix_purchase_orders_company_supplier_status", "purchase_orders",
                    ["company_id", "supplier_id", "status"])

    op.create_table(
        "purchase_order_lines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("purchase_order_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("ordered_quantity", sa.Numeric(12, 3), nullable=False),
        sa.Column("received_quantity", sa.Numeric(12, 3), server_default="0", nullable=False),
        sa.Column("unit_cost", sa.Numeric(12, 2), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "id", name="uq_purchase_order_lines_company_id"),
        sa.UniqueConstraint("company_id", "purchase_order_id", "product_id",
                            name="uq_purchase_order_line_product"),
        sa.ForeignKeyConstraint(
            ["company_id", "purchase_order_id"],
            ["purchase_orders.company_id", "purchase_orders.id"],
            ondelete="NO ACTION", name="fk_purchase_order_lines_order_same_company",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "product_id"], ["products.company_id", "products.id"],
            ondelete="NO ACTION", name="fk_purchase_order_lines_product_same_company",
        ),
        sa.CheckConstraint("ordered_quantity > 0", name="purchase_order_ordered_qty_positive"),
        sa.CheckConstraint("received_quantity >= 0 AND received_quantity <= ordered_quantity",
                           name="purchase_order_received_qty_in_range"),
        sa.CheckConstraint("unit_cost >= 0", name="purchase_order_unit_cost_nonnegative"),
    )
    op.create_index("ix_purchase_order_lines_company_order", "purchase_order_lines",
                    ["company_id", "purchase_order_id"])

    op.create_table(
        "purchase_order_receipts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("purchase_order_id", sa.Uuid(), nullable=False),
        sa.Column("supplier_id", sa.Uuid(), nullable=False),
        sa.Column("delivery_note_reference", sa.String(length=120), nullable=False),
        sa.Column("supplier_invoice_reference", sa.String(length=120), nullable=True),
        sa.Column("received_by_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "received_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "id", name="uq_purchase_order_receipts_company_id"),
        sa.UniqueConstraint("company_id", "supplier_id", "delivery_note_reference",
                            name="uq_purchase_receipt_delivery_note"),
        sa.ForeignKeyConstraint(
            ["company_id", "purchase_order_id"],
            ["purchase_orders.company_id", "purchase_orders.id"],
            ondelete="NO ACTION", name="fk_purchase_receipts_order_same_company",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "supplier_id"], ["suppliers.company_id", "suppliers.id"],
            ondelete="NO ACTION", name="fk_purchase_receipts_supplier_same_company",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "received_by_user_id"],
            ["company_memberships.company_id", "company_memberships.user_id"],
            ondelete="NO ACTION", name="fk_purchase_receipts_receiver_membership",
        ),
        sa.CheckConstraint("length(trim(delivery_note_reference)) > 0",
                           name="purchase_receipt_delivery_note_not_empty"),
    )
    op.create_index("ix_purchase_receipts_company_order", "purchase_order_receipts",
                    ["company_id", "purchase_order_id", "received_at"])

    op.create_table(
        "purchase_order_receipt_lines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("receipt_id", sa.Uuid(), nullable=False),
        sa.Column("purchase_order_line_id", sa.Uuid(), nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.Numeric(12, 3), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "receipt_id", "purchase_order_line_id",
                            name="uq_purchase_receipt_line_order_line"),
        sa.ForeignKeyConstraint(
            ["company_id", "receipt_id"],
            ["purchase_order_receipts.company_id", "purchase_order_receipts.id"],
            ondelete="NO ACTION", name="fk_purchase_receipt_lines_receipt_same_company",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "purchase_order_line_id"],
            ["purchase_order_lines.company_id", "purchase_order_lines.id"],
            ondelete="NO ACTION", name="fk_purchase_receipt_lines_order_line_same_company",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "batch_id"], ["stock_batches.company_id", "id"],
            ondelete="NO ACTION", name="fk_purchase_receipt_lines_batch_same_company",
        ),
        sa.CheckConstraint("quantity > 0", name="purchase_receipt_line_qty_positive"),
    )
    op.create_index("ix_purchase_receipt_lines_company_receipt", "purchase_order_receipt_lines",
                    ["company_id", "receipt_id"])

    for table in (
        "purchase_orders", "purchase_order_lines",
        "purchase_order_receipts", "purchase_order_receipt_lines",
    ):
        _tenant_table(table)

    op.drop_constraint("event_type_is_supported", "audit_logs", type_="check")
    op.create_check_constraint(
        "event_type_is_supported", "audit_logs",
        "event_type IN ('login_succeeded', 'password_changed', 'company_selected', 'logout', "
        "'email_verified', 'password_reset', 'company_invitation_created', "
        "'company_invitation_accepted', 'company_invitation_revoked', 'mfa_enabled', "
        "'mfa_disabled', 'mfa_recovery_code_used', 'company_settings_updated', "
        "'team_member_role_changed', 'team_member_suspended', 'team_member_reactivated', "
        "'product_created', 'product_updated', 'discount_limits_updated', "
        "'discount_approval_requested', 'discount_approval_decided', 'price_floor_override', "
        "'discount_applied', 'product_compliance_verified', 'product_compliance_rejected', "
        "'product_compliance_recalled', 'product_compliance_exception', "
        "'product_compliance_policy_updated', 'product_compliance_evidence_uploaded', "
        "'product_compliance_evidence_downloaded', 'product_compliance_not_required_release', "
        "'supplier_created', 'supplier_approved', 'supplier_restricted', 'supplier_suspended', "
        "'supplier_rejected', 'supplier_re_review_required', 'supplier_document_uploaded', "
        "'supplier_document_rejected', 'supplier_document_downloaded', "
        "'purchase_order_created', 'purchase_order_receipt_recorded')",
    )


def downgrade():
    op.execute(
        "UPDATE audit_logs SET event_type = 'supplier_re_review_required' "
        "WHERE event_type IN ('purchase_order_created', 'purchase_order_receipt_recorded')"
    )
    op.drop_constraint("event_type_is_supported", "audit_logs", type_="check")
    op.create_check_constraint(
        "event_type_is_supported", "audit_logs",
        "event_type IN ('login_succeeded', 'password_changed', 'company_selected', 'logout', "
        "'email_verified', 'password_reset', 'company_invitation_created', "
        "'company_invitation_accepted', 'company_invitation_revoked', 'mfa_enabled', "
        "'mfa_disabled', 'mfa_recovery_code_used', 'company_settings_updated', "
        "'team_member_role_changed', 'team_member_suspended', 'team_member_reactivated', "
        "'product_created', 'product_updated', 'discount_limits_updated', "
        "'discount_approval_requested', 'discount_approval_decided', 'price_floor_override', "
        "'discount_applied', 'product_compliance_verified', 'product_compliance_rejected', "
        "'product_compliance_recalled', 'product_compliance_exception', "
        "'product_compliance_policy_updated', 'product_compliance_evidence_uploaded', "
        "'product_compliance_evidence_downloaded', 'product_compliance_not_required_release', "
        "'supplier_created', 'supplier_approved', 'supplier_restricted', 'supplier_suspended', "
        "'supplier_rejected', 'supplier_re_review_required', 'supplier_document_uploaded', "
        "'supplier_document_rejected', 'supplier_document_downloaded')",
    )
    for table in (
        "purchase_order_receipt_lines", "purchase_order_receipts",
        "purchase_order_lines", "purchase_orders",
    ):
        op.execute(f"DROP POLICY IF EXISTS {table}_company_access ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
        op.execute(f"REVOKE SELECT, INSERT, UPDATE ON {table} FROM sales_dash_app")
    op.drop_index(
        "ix_purchase_receipt_lines_company_receipt",
        table_name="purchase_order_receipt_lines",
    )
    op.drop_table("purchase_order_receipt_lines")
    op.drop_index("ix_purchase_receipts_company_order", table_name="purchase_order_receipts")
    op.drop_table("purchase_order_receipts")
    op.drop_index("ix_purchase_order_lines_company_order", table_name="purchase_order_lines")
    op.drop_table("purchase_order_lines")
    op.drop_index("ix_purchase_orders_company_supplier_status", table_name="purchase_orders")
    op.drop_table("purchase_orders")
