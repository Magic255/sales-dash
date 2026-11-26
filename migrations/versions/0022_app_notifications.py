"""Add private in-app notifications for discount approval requests.

Revision ID: 0022_app_notifications
Revises: 0021_inventory_batches_expiry
"""

# ruff: noqa: I001
from alembic import op
import sqlalchemy as sa


revision = "0022_app_notifications"
down_revision = "0021_inventory_batches_expiry"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "app_notifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("recipient_user_id", sa.Uuid(), nullable=False),
        sa.Column("related_sale_id", sa.Uuid(), nullable=True),
        sa.Column("notification_type", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("message", sa.String(length=500), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"],
            name="fk_app_notifications_company_id_companies",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "recipient_user_id"],
            ["company_memberships.company_id", "company_memberships.user_id"],
            name="fk_app_notifications_recipient_membership",
            ondelete="NO ACTION",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "related_sale_id"],
            ["sales.company_id", "sales.id"],
            name="fk_app_notifications_sale_same_company",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "notification_type IN ('discount_approval_requested', 'discount_approval_decided')",
            name="notification_type_is_supported",
        ),
        sa.CheckConstraint("length(trim(title)) > 0", name="title_not_empty"),
        sa.CheckConstraint("length(trim(message)) > 0", name="message_not_empty"),
    )
    op.create_index(
        "ix_app_notifications_recipient_unread",
        "app_notifications",
        ["company_id", "recipient_user_id", "read_at", "created_at"],
    )
    op.execute("REVOKE ALL ON app_notifications FROM sales_dash_app")
    op.execute("GRANT SELECT, INSERT ON app_notifications TO sales_dash_app")
    op.execute("GRANT UPDATE (read_at) ON app_notifications TO sales_dash_app")
    op.execute("ALTER TABLE app_notifications ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE app_notifications FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY app_notifications_recipient_select
        ON app_notifications
        FOR SELECT TO sales_dash_app
        USING (
            company_id =
                NULLIF(current_setting('app.current_company_id', true), '')::uuid
            AND recipient_user_id =
                NULLIF(current_setting('app.current_user_id', true), '')::uuid
        )
        """
    )
    op.execute(
        """
        CREATE POLICY app_notifications_company_insert
        ON app_notifications
        FOR INSERT TO sales_dash_app
        WITH CHECK (
            company_id =
                NULLIF(current_setting('app.current_company_id', true), '')::uuid
        )
        """
    )
    op.execute(
        """
        CREATE POLICY app_notifications_recipient_update
        ON app_notifications
        FOR UPDATE TO sales_dash_app
        USING (
            company_id =
                NULLIF(current_setting('app.current_company_id', true), '')::uuid
            AND recipient_user_id =
                NULLIF(current_setting('app.current_user_id', true), '')::uuid
        )
        WITH CHECK (
            company_id =
                NULLIF(current_setting('app.current_company_id', true), '')::uuid
            AND recipient_user_id =
                NULLIF(current_setting('app.current_user_id', true), '')::uuid
        )
        """
    )


def downgrade():
    op.execute(
        "DROP POLICY IF EXISTS app_notifications_recipient_update ON app_notifications"
    )
    op.execute(
        "DROP POLICY IF EXISTS app_notifications_company_insert ON app_notifications"
    )
    op.execute(
        "DROP POLICY IF EXISTS app_notifications_recipient_select ON app_notifications"
    )
    op.execute("ALTER TABLE app_notifications NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE app_notifications DISABLE ROW LEVEL SECURITY")
    op.execute("REVOKE UPDATE (read_at) ON app_notifications FROM sales_dash_app")
    op.execute("REVOKE SELECT, INSERT ON app_notifications FROM sales_dash_app")
    op.drop_index(
        "ix_app_notifications_recipient_unread", table_name="app_notifications"
    )
    op.drop_table("app_notifications")
