"""Add batch-level compliance quarantine and verification metadata.

Revision ID: 0024_product_compliance
Revises: 0023_expiry_alerts
"""

# ruff: noqa: I001
from alembic import op
import sqlalchemy as sa

revision = "0024_product_compliance"
down_revision = "0023_expiry_alerts"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "products",
        sa.Column("compliance_required", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "stock_batches",
        sa.Column("compliance_status", sa.String(length=24), nullable=False, server_default="approved"),
    )
    op.add_column(
        "stock_batches",
        sa.Column("received_by_user_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "stock_batches",
        sa.Column("qr_code", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "stock_batches",
        sa.Column("authority_name", sa.String(length=160), nullable=True),
    )
    op.add_column(
        "stock_batches",
        sa.Column("authority_country", sa.String(length=2), nullable=True),
    )
    op.add_column(
        "stock_batches",
        sa.Column("standard_reference", sa.String(length=160), nullable=True),
    )
    op.add_column(
        "stock_batches",
        sa.Column("certificate_reference", sa.String(length=160), nullable=True),
    )
    op.add_column(
        "stock_batches",
        sa.Column("evidence_reference", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "stock_batches",
        sa.Column("verified_by_user_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "stock_batches",
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "stock_batches",
        sa.Column("verification_notes", sa.String(length=1000), nullable=True),
    )
    op.create_check_constraint(
        "compliance_status_supported",
        "stock_batches",
        "compliance_status IN ('approved', 'pending_verification', 'rejected', 'recalled')",
    )
    op.create_foreign_key(
        "fk_stock_batches_receiver_membership",
        "stock_batches", "company_memberships",
        ["company_id", "received_by_user_id"], ["company_id", "user_id"],
        ondelete="NO ACTION",
    )
    op.create_foreign_key(
        "fk_stock_batches_verifier_membership",
        "stock_batches", "company_memberships",
        ["company_id", "verified_by_user_id"], ["company_id", "user_id"],
        ondelete="NO ACTION",
    )
    op.execute("GRANT UPDATE (compliance_required) ON products TO sales_dash_app")
    op.execute(
        "GRANT UPDATE (compliance_status, qr_code, authority_name, authority_country, "
        "standard_reference, certificate_reference, evidence_reference, verified_by_user_id, "
        "verified_at, verification_notes) ON stock_batches TO sales_dash_app"
    )
    op.drop_constraint("event_type_is_supported", "audit_logs", type_="check")
    op.create_check_constraint(
        "event_type_is_supported", "audit_logs",
        "event_type IN ('login_succeeded', 'password_changed', 'company_selected', "
        "'logout', 'email_verified', 'password_reset', 'company_invitation_created', "
        "'company_invitation_accepted', 'company_invitation_revoked', 'mfa_enabled', "
        "'mfa_disabled', 'mfa_recovery_code_used', 'company_settings_updated', "
        "'team_member_role_changed', 'team_member_suspended', 'team_member_reactivated', "
        "'product_created', 'product_updated', 'discount_limits_updated', "
        "'discount_approval_requested', 'discount_approval_decided', "
        "'price_floor_override', 'discount_applied', 'product_compliance_verified', "
        "'product_compliance_rejected', 'product_compliance_recalled')",
    )


def downgrade():
    op.drop_constraint("event_type_is_supported", "audit_logs", type_="check")
    op.create_check_constraint(
        "event_type_is_supported", "audit_logs",
        "event_type IN ('login_succeeded', 'password_changed', 'company_selected', "
        "'logout', 'email_verified', 'password_reset', 'company_invitation_created', "
        "'company_invitation_accepted', 'company_invitation_revoked', 'mfa_enabled', "
        "'mfa_disabled', 'mfa_recovery_code_used', 'company_settings_updated', "
        "'team_member_role_changed', 'team_member_suspended', 'team_member_reactivated', "
        "'product_created', 'product_updated', 'discount_limits_updated', "
        "'discount_approval_requested', 'discount_approval_decided', "
        "'price_floor_override', 'discount_applied')",
    )
    op.execute(
        "REVOKE UPDATE (compliance_required) ON products FROM sales_dash_app"
    )
    op.execute(
        "REVOKE UPDATE (compliance_status, qr_code, authority_name, authority_country, "
        "standard_reference, certificate_reference, evidence_reference, verified_by_user_id, "
        "verified_at, verification_notes) ON stock_batches FROM sales_dash_app"
    )
    op.drop_constraint("fk_stock_batches_verifier_membership", "stock_batches", type_="foreignkey")
    op.drop_constraint("fk_stock_batches_receiver_membership", "stock_batches", type_="foreignkey")
    op.drop_constraint("compliance_status_supported", "stock_batches", type_="check")
    for column in (
        "verification_notes", "verified_at", "verified_by_user_id", "evidence_reference",
        "certificate_reference", "standard_reference", "authority_country", "authority_name",
        "qr_code", "received_by_user_id", "compliance_status",
    ):
        op.drop_column("stock_batches", column)
    op.drop_column("products", "compliance_required")
