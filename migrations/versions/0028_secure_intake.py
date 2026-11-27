"""Add supplier provenance and non-overridable legal compliance policies.

Revision ID: 0028_secure_intake
Revises: 0027_verification_sources
"""

# ruff: noqa: I001
from alembic import op
import sqlalchemy as sa


revision = "0028_secure_intake"
down_revision = "0027_verification_sources"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("stock_batches", sa.Column("supplier_name", sa.String(length=160)))
    op.add_column(
        "stock_batches",
        sa.Column("supplier_invoice_reference", sa.String(length=120)),
    )
    op.add_column(
        "stock_batches",
        sa.Column("delivery_note_reference", sa.String(length=120)),
    )
    op.add_column("stock_batches", sa.Column("manufacturer_name", sa.String(length=160)))
    op.add_column("stock_batches", sa.Column("country_of_origin", sa.String(length=2)))
    op.create_check_constraint(
        "country_of_origin_iso_code",
        "stock_batches",
        "country_of_origin IS NULL OR "
        "(country_of_origin = upper(country_of_origin) AND length(country_of_origin) = 2)",
    )
    op.execute(
        "UPDATE stock_batches SET compliance_status = 'pending_verification' "
        "WHERE compliance_status = 'approved'"
    )
    op.drop_constraint("compliance_status_supported", "stock_batches", type_="check")
    op.alter_column(
        "stock_batches", "compliance_status",
        existing_type=sa.String(length=24),
        server_default="pending_verification",
    )
    op.create_check_constraint(
        "compliance_status_supported",
        "stock_batches",
        "compliance_status IN ('approved', 'exception_approved', "
        "'verified_not_required', 'pending_verification', 'rejected', 'recalled')",
    )
    op.add_column(
        "category_compliance_policies",
        sa.Column(
            "legal_requirement",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "category_compliance_policies",
        sa.Column("requirement_source_url", sa.String(length=500)),
    )
    op.add_column(
        "category_compliance_policies",
        sa.Column("requirement_reference", sa.String(length=200)),
    )
    op.create_check_constraint(
        "legal_requirement_no_exception",
        "category_compliance_policies",
        "NOT legal_requirement OR approval_mode = 'required'",
    )
    op.create_check_constraint(
        "requirement_source_https",
        "category_compliance_policies",
        "requirement_source_url IS NULL OR requirement_source_url LIKE 'https://%'",
    )
    op.execute(
        "GRANT UPDATE (supplier_name, supplier_invoice_reference, delivery_note_reference, "
        "manufacturer_name, country_of_origin) ON stock_batches TO sales_dash_app"
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
        "'product_compliance_policy_updated', 'product_compliance_evidence_uploaded', "
        "'product_compliance_evidence_downloaded', "
        "'product_compliance_not_required_release')",
    )
    op.execute(
        "GRANT UPDATE (legal_requirement, requirement_source_url, requirement_reference) "
        "ON category_compliance_policies TO sales_dash_app"
    )


def downgrade():
    op.execute(
        "UPDATE stock_batches SET compliance_status = 'pending_verification' "
        "WHERE compliance_status = 'verified_not_required'"
    )
    op.execute(
        "UPDATE audit_logs SET event_type = 'product_compliance_verified' "
        "WHERE event_type = 'product_compliance_not_required_release'"
    )
    op.execute(
        "REVOKE UPDATE (supplier_name, supplier_invoice_reference, delivery_note_reference, "
        "manufacturer_name, country_of_origin) ON stock_batches FROM sales_dash_app"
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
        "'product_compliance_policy_updated', 'product_compliance_evidence_uploaded', "
        "'product_compliance_evidence_downloaded')",
    )
    op.execute(
        "REVOKE UPDATE (legal_requirement, requirement_source_url, requirement_reference) "
        "ON category_compliance_policies FROM sales_dash_app"
    )
    op.drop_constraint(
        "requirement_source_https", "category_compliance_policies", type_="check"
    )
    op.drop_constraint(
        "legal_requirement_no_exception", "category_compliance_policies", type_="check"
    )
    op.drop_column("category_compliance_policies", "requirement_reference")
    op.drop_column("category_compliance_policies", "requirement_source_url")
    op.drop_column("category_compliance_policies", "legal_requirement")
    op.drop_constraint("compliance_status_supported", "stock_batches", type_="check")
    op.alter_column(
        "stock_batches", "compliance_status",
        existing_type=sa.String(length=24),
        server_default="approved",
    )
    op.create_check_constraint(
        "compliance_status_supported",
        "stock_batches",
        "compliance_status IN ('approved', 'exception_approved', "
        "'pending_verification', 'rejected', 'recalled')",
    )
    op.drop_constraint("country_of_origin_iso_code", "stock_batches", type_="check")
    for column in (
        "country_of_origin",
        "manufacturer_name",
        "delivery_note_reference",
        "supplier_invoice_reference",
        "supplier_name",
    ):
        op.drop_column("stock_batches", column)
