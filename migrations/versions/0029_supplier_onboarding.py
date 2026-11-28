"""Add tenant-scoped supplier onboarding and independent review.

Revision ID: 0029_supplier_onboarding
Revises: 0028_secure_intake
"""

# ruff: noqa: I001
from alembic import op
import sqlalchemy as sa


revision = "0029_supplier_onboarding"
down_revision = "0028_secure_intake"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "suppliers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("legal_name", sa.String(length=180), nullable=False),
        sa.Column("registration_number", sa.String(length=120)),
        sa.Column("tax_identifier", sa.String(length=120)),
        sa.Column("country", sa.String(length=2), nullable=False),
        sa.Column("address", sa.String(length=500)),
        sa.Column("contact_name", sa.String(length=160)),
        sa.Column("contact_email", sa.String(length=320)),
        sa.Column("contact_phone", sa.String(length=40)),
        sa.Column("authorised_categories", sa.JSON(), nullable=False),
        sa.Column("authorised_brands", sa.JSON(), nullable=False),
        sa.Column("authorised_territories", sa.JSON(), nullable=False),
        sa.Column("licence_number", sa.String(length=160)),
        sa.Column("licence_issuer", sa.String(length=180)),
        sa.Column("licence_source_url", sa.String(length=500)),
        sa.Column("licence_valid_until", sa.Date()),
        sa.Column("next_review_date", sa.Date()),
        sa.Column("status", sa.String(length=24), nullable=False,
                  server_default="pending_review"),
        sa.Column("submitted_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("reviewed_by_user_id", sa.Uuid()),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("review_notes", sa.String(length=1000)),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "id", name="uq_suppliers_company_id_id"),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"],
            ondelete="CASCADE", name="fk_suppliers_company",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "submitted_by_user_id"],
            ["company_memberships.company_id", "company_memberships.user_id"],
            ondelete="NO ACTION", name="fk_suppliers_submitter_membership",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "reviewed_by_user_id"],
            ["company_memberships.company_id", "company_memberships.user_id"],
            ondelete="NO ACTION", name="fk_suppliers_reviewer_membership",
        ),
        sa.CheckConstraint(
            "status IN ('pending_review', 'approved', 'restricted', "
            "'suspended', 'rejected', 'expired')",
            name="supplier_status_supported",
        ),
        sa.CheckConstraint("length(trim(legal_name)) > 0",
                           name="supplier_legal_name_not_empty"),
        sa.CheckConstraint(
            "country = upper(country) AND length(country) = 2",
            name="supplier_country_iso_code",
        ),
        sa.CheckConstraint(
            "reviewed_by_user_id IS NULL OR reviewed_by_user_id <> submitted_by_user_id",
            name="supplier_no_self_approval",
        ),
        sa.CheckConstraint(
            "licence_source_url IS NULL OR licence_source_url LIKE 'https://%'",
            name="supplier_licence_source_https",
        ),
    )
    op.create_index(
        "ix_suppliers_company_status", "suppliers", ["company_id", "status"]
    )
    op.create_index(
        "ix_suppliers_company_licence_expiry",
        "suppliers", ["company_id", "licence_valid_until"],
    )
    op.execute("REVOKE ALL ON suppliers FROM sales_dash_app")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON suppliers TO sales_dash_app"
    )
    op.execute("ALTER TABLE suppliers ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE suppliers FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY suppliers_company_access
        ON suppliers
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
        "'product_compliance_evidence_downloaded', "
        "'product_compliance_not_required_release', "
        "'supplier_created', 'supplier_approved', 'supplier_restricted', "
        "'supplier_suspended', 'supplier_rejected', 'supplier_re_review_required')",
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
        "'product_compliance_policy_updated', "
        "'product_compliance_evidence_uploaded', "
        "'product_compliance_evidence_downloaded', "
        "'product_compliance_not_required_release')",
    )
    op.execute(
        "DROP POLICY IF EXISTS suppliers_company_access ON suppliers"
    )
    op.execute("ALTER TABLE suppliers NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE suppliers DISABLE ROW LEVEL SECURITY")
    op.execute("REVOKE SELECT, INSERT, UPDATE ON suppliers FROM sales_dash_app")
    op.drop_index("ix_suppliers_company_licence_expiry", table_name="suppliers")
    op.drop_index("ix_suppliers_company_status", table_name="suppliers")
    op.drop_table("suppliers")
