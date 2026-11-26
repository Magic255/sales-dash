"""Add encrypted private evidence files for compliance review.

Revision ID: 0026_private_evidence
Revises: 0025_category_compliance
"""

# ruff: noqa: I001
from alembic import op
import sqlalchemy as sa


revision = "0026_private_evidence"
down_revision = "0025_category_compliance"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "compliance_evidence_files",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("uploaded_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("original_filename", sa.String(length=180), nullable=False),
        sa.Column("content_type", sa.String(length=80), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("encrypted_content", sa.LargeBinary(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "company_id", "id", name="uq_compliance_evidence_company_id"
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "batch_id"],
            ["stock_batches.company_id", "stock_batches.id"],
            ondelete="NO ACTION",
            name="fk_compliance_evidence_batch_same_company",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "uploaded_by_user_id"],
            ["company_memberships.company_id", "company_memberships.user_id"],
            ondelete="NO ACTION",
            name="fk_compliance_evidence_uploader_membership",
        ),
        sa.CheckConstraint(
            "length(trim(original_filename)) > 0",
            name="filename_not_empty",
        ),
        sa.CheckConstraint(
            "content_type IN ('application/pdf', 'image/jpeg', 'image/png', 'image/webp')",
            name="content_type_supported",
        ),
        sa.CheckConstraint(
            "size_bytes > 0 AND size_bytes <= 8388608",
            name="size_bytes_supported",
        ),
        sa.CheckConstraint("length(sha256) = 64", name="sha256_length"),
    )
    op.create_index(
        "ix_compliance_evidence_company_batch",
        "compliance_evidence_files",
        ["company_id", "batch_id", "created_at"],
    )
    op.execute(
        "REVOKE ALL ON compliance_evidence_files FROM sales_dash_app"
    )
    op.execute(
        "GRANT SELECT, INSERT ON compliance_evidence_files TO sales_dash_app"
    )
    op.execute(
        "ALTER TABLE compliance_evidence_files ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        "ALTER TABLE compliance_evidence_files FORCE ROW LEVEL SECURITY"
    )
    op.execute(
        """
        CREATE POLICY compliance_evidence_company_access
        ON compliance_evidence_files
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
    op.create_check_constraint(
        "event_type_is_supported",
        "audit_logs",
        "event_type IN ('login_succeeded', 'password_changed', "
        "'company_selected', 'logout', 'email_verified', 'password_reset', "
        "'company_invitation_created', 'company_invitation_accepted', "
        "'company_invitation_revoked', 'mfa_enabled', 'mfa_disabled', "
        "'mfa_recovery_code_used', 'company_settings_updated', "
        "'team_member_role_changed', 'team_member_suspended', "
        "'team_member_reactivated', 'product_created', 'product_updated', "
        "'discount_limits_updated', 'discount_approval_requested', "
        "'discount_approval_decided', 'price_floor_override', 'discount_applied', "
        "'product_compliance_verified', 'product_compliance_rejected', "
        "'product_compliance_recalled', 'product_compliance_exception', "
        "'product_compliance_policy_updated', "
        "'product_compliance_evidence_uploaded', "
        "'product_compliance_evidence_downloaded')",
    )


def downgrade():
    op.drop_constraint("event_type_is_supported", "audit_logs", type_="check")
    op.create_check_constraint(
        "event_type_is_supported",
        "audit_logs",
        "event_type IN ('login_succeeded', 'password_changed', "
        "'company_selected', 'logout', 'email_verified', 'password_reset', "
        "'company_invitation_created', 'company_invitation_accepted', "
        "'company_invitation_revoked', 'mfa_enabled', 'mfa_disabled', "
        "'mfa_recovery_code_used', 'company_settings_updated', "
        "'team_member_role_changed', 'team_member_suspended', "
        "'team_member_reactivated', 'product_created', 'product_updated', "
        "'discount_limits_updated', 'discount_approval_requested', "
        "'discount_approval_decided', 'price_floor_override', 'discount_applied', "
        "'product_compliance_verified', 'product_compliance_rejected', "
        "'product_compliance_recalled', 'product_compliance_exception', "
        "'product_compliance_policy_updated')",
    )
    op.execute(
        "DROP POLICY IF EXISTS compliance_evidence_company_access "
        "ON compliance_evidence_files"
    )
    op.execute(
        "ALTER TABLE compliance_evidence_files NO FORCE ROW LEVEL SECURITY"
    )
    op.execute(
        "ALTER TABLE compliance_evidence_files DISABLE ROW LEVEL SECURITY"
    )
    op.execute(
        "REVOKE SELECT, INSERT ON compliance_evidence_files FROM sales_dash_app"
    )
    op.drop_index(
        "ix_compliance_evidence_company_batch",
        table_name="compliance_evidence_files",
    )
    op.drop_table("compliance_evidence_files")
