"""Create tenant-isolated append-only security audit logs.

Revision ID: 0005_security_audit_logs
Revises: 0004_user_auth_version
"""

# ruff: noqa: I001
from alembic import op
import sqlalchemy as sa


revision = "0005_security_audit_logs"
down_revision = "0004_user_auth_version"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("company_id", sa.Uuid(), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "event_type IN ('login_succeeded', 'password_changed', "
            "'company_selected', 'logout')",
            name="event_type_is_supported",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_logs")),
    )
    op.create_index("ix_audit_logs_company_time", "audit_logs", ["company_id", "occurred_at"])
    op.create_index("ix_audit_logs_actor_time", "audit_logs", ["actor_user_id", "occurred_at"])

    op.execute("GRANT SELECT, INSERT ON audit_logs TO sales_dash_app")
    op.execute("ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audit_logs FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY audit_logs_read_scoped ON audit_logs
        FOR SELECT TO sales_dash_app
        USING (
            (
                company_id IS NOT NULL
                AND company_id =
                    NULLIF(current_setting('app.current_company_id', true), '')::uuid
            )
            OR (
                company_id IS NULL
                AND actor_user_id =
                    NULLIF(current_setting('app.current_user_id', true), '')::uuid
            )
        )
        """
    )
    op.execute(
        """
        CREATE POLICY audit_logs_insert_self ON audit_logs
        FOR INSERT TO sales_dash_app
        WITH CHECK (
            actor_user_id =
                NULLIF(current_setting('app.current_user_id', true), '')::uuid
            AND (
                (
                    company_id IS NULL
                    AND NULLIF(current_setting('app.current_company_id', true), '') IS NULL
                )
                OR company_id =
                    NULLIF(current_setting('app.current_company_id', true), '')::uuid
            )
        )
        """
    )


def downgrade():
    op.execute("DROP POLICY IF EXISTS audit_logs_insert_self ON audit_logs")
    op.execute("DROP POLICY IF EXISTS audit_logs_read_scoped ON audit_logs")
    op.execute("ALTER TABLE audit_logs NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audit_logs DISABLE ROW LEVEL SECURITY")
    op.execute("REVOKE SELECT, INSERT ON audit_logs FROM sales_dash_app")
    op.drop_index("ix_audit_logs_actor_time", table_name="audit_logs")
    op.drop_index("ix_audit_logs_company_time", table_name="audit_logs")
    op.drop_table("audit_logs")
