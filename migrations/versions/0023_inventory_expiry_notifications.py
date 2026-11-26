"""Add deduplicated inventory batch expiry notifications.

Revision ID: 0023_inventory_expiry_notifications
Revises: 0022_app_notifications
"""

# ruff: noqa: I001
from alembic import op
import sqlalchemy as sa


revision = "0023_inventory_expiry_notifications"
down_revision = "0022_app_notifications"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "app_notifications",
        sa.Column("related_batch_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "app_notifications",
        sa.Column("dedupe_key", sa.String(length=160), nullable=True),
    )
    op.create_foreign_key(
        "fk_app_notifications_batch_same_company",
        "app_notifications",
        "stock_batches",
        ["company_id", "related_batch_id"],
        ["company_id", "id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        "uq_app_notifications_recipient_dedupe",
        "app_notifications",
        ["company_id", "recipient_user_id", "dedupe_key"],
    )
    op.drop_constraint(
        "notification_type_is_supported",
        "app_notifications",
        type_="check",
    )
    op.create_check_constraint(
        "notification_type_is_supported",
        "app_notifications",
        "notification_type IN ("
        "'discount_approval_requested', 'discount_approval_decided', "
        "'inventory_batch_expiring', 'inventory_batch_expired')",
    )

    # Inventory expiry alerts are routed to active Admins and Managers only.
    op.execute("DROP POLICY memberships_read_company_admins ON company_memberships")
    op.execute(
        """
        CREATE POLICY memberships_read_company_admins
        ON company_memberships
        FOR SELECT TO sales_dash_app
        USING (
            role IN ('admin', 'manager')
            AND status = 'active'
            AND company_id =
                NULLIF(current_setting('app.current_company_id', true), '')::uuid
        )
        """
    )


def downgrade():
    op.execute("DROP POLICY memberships_read_company_admins ON company_memberships")
    op.execute(
        """
        CREATE POLICY memberships_read_company_admins
        ON company_memberships
        FOR SELECT TO sales_dash_app
        USING (
            role = 'admin'
            AND status = 'active'
            AND company_id =
                NULLIF(current_setting('app.current_company_id', true), '')::uuid
        )
        """
    )
    op.drop_constraint(
        "notification_type_is_supported",
        "app_notifications",
        type_="check",
    )
    op.create_check_constraint(
        "notification_type_is_supported",
        "app_notifications",
        "notification_type IN "
        "('discount_approval_requested', 'discount_approval_decided')",
    )
    op.drop_constraint(
        "uq_app_notifications_recipient_dedupe",
        "app_notifications",
        type_="unique",
    )
    op.drop_constraint(
        "fk_app_notifications_batch_same_company",
        "app_notifications",
        type_="foreignkey",
    )
    op.drop_column("app_notifications", "dedupe_key")
    op.drop_column("app_notifications", "related_batch_id")
