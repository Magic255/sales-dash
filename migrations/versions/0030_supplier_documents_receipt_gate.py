"""Add scanned supplier documents and bind receipts to approved suppliers.

Revision ID: 0030_supplier_documents_receipt_gate
Revises: 0029_supplier_onboarding
"""

# ruff: noqa: I001
from alembic import op
import sqlalchemy as sa


revision = "0030_supplier_documents_receipt_gate"
down_revision = "0029_supplier_onboarding"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("stock_batches", sa.Column("supplier_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_stock_batches_supplier_same_company", "stock_batches", "suppliers",
        ["company_id", "supplier_id"], ["company_id", "id"], ondelete="NO ACTION",
    )
    op.create_table(
        "supplier_documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("supplier_id", sa.Uuid(), nullable=False),
        sa.Column("uploaded_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("original_filename", sa.String(length=180), nullable=False),
        sa.Column("content_type", sa.String(length=80), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("encrypted_content", sa.LargeBinary(), nullable=False),
        sa.Column("scan_status", sa.String(length=16), nullable=False, server_default="clean"),
        sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "id", name="uq_supplier_documents_company_id"),
        sa.ForeignKeyConstraint(
            ["company_id", "supplier_id"], ["suppliers.company_id", "suppliers.id"],
            ondelete="NO ACTION", name="fk_supplier_documents_supplier_same_company",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "uploaded_by_user_id"],
            ["company_memberships.company_id", "company_memberships.user_id"],
            ondelete="NO ACTION", name="fk_supplier_documents_uploader_membership",
        ),
        sa.CheckConstraint(
            "content_type IN ('application/pdf', 'image/jpeg', 'image/png', 'image/webp')",
            name="supplier_document_content_type_supported",
        ),
        sa.CheckConstraint(
            "size_bytes > 0 AND size_bytes <= 8388608",
            name="supplier_document_size_supported",
        ),
        sa.CheckConstraint("length(sha256) = 64", name="supplier_document_sha256_length"),
        sa.CheckConstraint("scan_status = 'clean'", name="supplier_document_must_be_clean"),
    )
    op.create_index(
        "ix_supplier_documents_company_supplier", "supplier_documents",
        ["company_id", "supplier_id", "created_at"],
    )
    op.execute("REVOKE ALL ON supplier_documents FROM sales_dash_app")
    op.execute("GRANT SELECT, INSERT ON supplier_documents TO sales_dash_app")
    op.execute("ALTER TABLE supplier_documents ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE supplier_documents FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY supplier_documents_company_access ON supplier_documents
        FOR ALL TO sales_dash_app
        USING (company_id = NULLIF(current_setting('app.current_company_id', true), '')::uuid)
        WITH CHECK (company_id = NULLIF(current_setting('app.current_company_id', true), '')::uuid)
    """)
    op.execute("GRANT UPDATE (supplier_id) ON stock_batches TO sales_dash_app")
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


def downgrade():
    op.execute(
        "UPDATE audit_logs SET event_type = 'supplier_re_review_required' "
        "WHERE event_type IN ('supplier_document_uploaded', 'supplier_document_rejected', "
        "'supplier_document_downloaded')"
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
        "'supplier_rejected', 'supplier_re_review_required')",
    )
    op.execute("DROP POLICY IF EXISTS supplier_documents_company_access ON supplier_documents")
    op.execute("ALTER TABLE supplier_documents NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE supplier_documents DISABLE ROW LEVEL SECURITY")
    op.execute("REVOKE SELECT, INSERT ON supplier_documents FROM sales_dash_app")
    op.drop_index("ix_supplier_documents_company_supplier", table_name="supplier_documents")
    op.drop_table("supplier_documents")
    op.execute("REVOKE UPDATE (supplier_id) ON stock_batches FROM sales_dash_app")
    op.drop_constraint(
        "fk_stock_batches_supplier_same_company", "stock_batches", type_="foreignkey"
    )
    op.drop_column("stock_batches", "supplier_id")
