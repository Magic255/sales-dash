"""Add product cost and minimum selling price controls.

Revision ID: 0019_product_price_floor
Revises: 0018_discount_approvals
"""

import sqlalchemy as sa
from alembic import op


revision = "0019_product_price_floor"
down_revision = "0018_discount_approvals"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "products",
        sa.Column("cost_price", sa.Numeric(12, 2), nullable=False, server_default="0"),
    )
    op.add_column(
        "products",
        sa.Column(
            "minimum_selling_price", sa.Numeric(12, 2),
            nullable=False, server_default="0",
        ),
    )
    op.create_check_constraint(
        "cost_price_nonnegative", "products", "cost_price >= 0"
    )
    op.create_check_constraint(
        "minimum_price_covers_cost", "products",
        "minimum_selling_price >= cost_price",
    )
    op.create_check_constraint(
        "unit_price_covers_floor", "products",
        "unit_price >= minimum_selling_price",
    )
    op.execute(
        "GRANT UPDATE (cost_price, minimum_selling_price) ON products TO sales_dash_app"
    )
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
        "'discount_approval_decided', 'price_floor_override')",
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
        "'discount_approval_decided')",
    )
    op.execute(
        "REVOKE UPDATE (cost_price, minimum_selling_price) ON products FROM sales_dash_app"
    )
    op.drop_constraint("unit_price_covers_floor", "products", type_="check")
    op.drop_constraint("minimum_price_covers_cost", "products", type_="check")
    op.drop_constraint("cost_price_nonnegative", "products", type_="check")
    op.drop_column("products", "minimum_selling_price")
    op.drop_column("products", "cost_price")
