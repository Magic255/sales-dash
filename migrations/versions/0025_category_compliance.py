"""Add tenant-scoped category and market compliance policies.

Revision ID: 0025_category_compliance
Revises: 0024_product_compliance
"""

# ruff: noqa: I001
from alembic import op
import sqlalchemy as sa


revision = "0025_category_compliance"
down_revision = "0024_product_compliance"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "products",
        sa.Column(
            "category_key", sa.String(length=80), nullable=False,
            server_default="general",
        ),
    )
    op.add_column(
        "products",
        sa.Column("market_country", sa.String(length=2), nullable=True),
    )
    op.create_check_constraint(
        "market_country_iso_code",
        "products",
        "market_country IS NULL OR "
        "(market_country = upper(market_country) AND length(market_country) = 2)",
    )
    op.execute(
        "GRANT UPDATE (category_key, market_country) ON products TO sales_dash_app"
    )

    op.create_table(
        "category_compliance_policies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("category_key", sa.String(length=80), nullable=False),
        sa.Column("market_country", sa.String(length=2), nullable=False),
        sa.Column("approval_mode", sa.String(length=24), nullable=False),
        sa.Column("accepted_authorities", sa.JSON(), nullable=False),
        sa.Column("updated_by_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "company_id", "category_key", "market_country",
            name="uq_compliance_policy_company_category_country",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"],
            name="fk_compliance_policy_company", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "updated_by_user_id"],
            ["company_memberships.company_id", "company_memberships.user_id"],
            name="fk_compliance_policy_updater_membership",
            ondelete="NO ACTION",
        ),
        sa.CheckConstraint(
            "approval_mode IN ('required', 'admin_exception', 'not_required')",
            name="approval_mode_supported",
        ),
        sa.CheckConstraint(
            "category_key = lower(trim(category_key)) AND length(category_key) > 0",
            name="category_key_normalized",
        ),
        sa.CheckConstraint(
            "market_country = upper(market_country) AND length(market_country) = 2",
            name="market_country_iso_code",
        ),
    )
    op.create_index(
        "ix_compliance_policies_company_country",
        "category_compliance_policies",
        ["company_id", "market_country"],
    )
    op.execute(
        "REVOKE ALL ON category_compliance_policies FROM sales_dash_app"
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE "
        "ON category_compliance_policies TO sales_dash_app"
    )
    op.execute(
        "ALTER TABLE category_compliance_policies ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        "ALTER TABLE category_compliance_policies FORCE ROW LEVEL SECURITY"
    )
    op.execute(
        """
        CREATE POLICY category_compliance_policy_company_access
        ON category_compliance_policies
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

    op.drop_constraint("compliance_status_supported", "stock_batches", type_="check")
    op.create_check_constraint(
        "compliance_status_supported",
        "stock_batches",
        "compliance_status IN "
        "('approved', 'exception_approved', 'pending_verification', 'rejected', 'recalled')",
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
        "'product_compliance_policy_updated')",
    )


def downgrade():
    op.drop_constraint("event_type_is_supported", "audit_logs", type_="check")
    op.create_check_constraint(
        "event_type_is_supported", "audit_logs",
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
        "'product_compliance_recalled')",
    )
    op.drop_constraint("compliance_status_supported", "stock_batches", type_="check")
    op.create_check_constraint(
        "compliance_status_supported", "stock_batches",
        "compliance_status IN "
        "('approved', 'pending_verification', 'rejected', 'recalled')",
    )
    op.execute(
        "DROP POLICY IF EXISTS category_compliance_policy_company_access "
        "ON category_compliance_policies"
    )
    op.execute(
        "ALTER TABLE category_compliance_policies NO FORCE ROW LEVEL SECURITY"
    )
    op.execute(
        "ALTER TABLE category_compliance_policies DISABLE ROW LEVEL SECURITY"
    )
    op.execute(
        "REVOKE SELECT, INSERT, UPDATE, DELETE "
        "ON category_compliance_policies FROM sales_dash_app"
    )
    op.drop_index(
        "ix_compliance_policies_company_country",
        table_name="category_compliance_policies",
    )
    op.drop_table("category_compliance_policies")
    op.execute(
        "REVOKE UPDATE (category_key, market_country) ON products FROM sales_dash_app"
    )
    op.drop_constraint("market_country_iso_code", "products", type_="check")
    op.drop_column("products", "market_country")
    op.drop_column("products", "category_key")
