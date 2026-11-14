"""Add restricted, single-use password reset tokens.

Revision ID: 0008_password_reset
Revises: 0007_email_verification
"""

# ruff: noqa: I001
from alembic import op
import sqlalchemy as sa


revision = "0008_password_reset"
down_revision = "0007_email_verification"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_password_reset_tokens_token_hash"),
    )
    op.create_index(
        "ix_password_reset_tokens_user_created",
        "password_reset_tokens",
        ["user_id", "created_at"],
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON password_reset_tokens TO sales_dash_app"
    )
    op.execute("ALTER TABLE password_reset_tokens ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE password_reset_tokens FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY password_reset_token_read ON password_reset_tokens
        FOR SELECT TO sales_dash_app
        USING (
            token_hash =
                NULLIF(current_setting('app.password_reset_token_hash', true), '')
            OR EXISTS (
                SELECT 1 FROM users
                WHERE users.id = password_reset_tokens.user_id
                  AND users.email =
                      NULLIF(current_setting('app.login_email', true), '')
            )
        )
        """
    )
    op.execute(
        """
        CREATE POLICY password_reset_token_redeem ON password_reset_tokens
        FOR UPDATE TO sales_dash_app
        USING (
            token_hash =
                NULLIF(current_setting('app.password_reset_token_hash', true), '')
        )
        WITH CHECK (
            token_hash =
                NULLIF(current_setting('app.password_reset_token_hash', true), '')
        )
        """
    )
    op.execute(
        """
        CREATE POLICY password_reset_token_create ON password_reset_tokens
        FOR INSERT TO sales_dash_app
        WITH CHECK (
            EXISTS (
                SELECT 1 FROM users
                WHERE users.id = password_reset_tokens.user_id
                  AND users.email =
                      NULLIF(current_setting('app.login_email', true), '')
            )
        )
        """
    )
    op.execute(
        """
        CREATE POLICY password_reset_token_replace ON password_reset_tokens
        FOR DELETE TO sales_dash_app
        USING (
            EXISTS (
                SELECT 1 FROM users
                WHERE users.id = password_reset_tokens.user_id
                  AND users.email =
                      NULLIF(current_setting('app.login_email', true), '')
            )
        )
        """
    )

    op.drop_constraint(
        op.f("ck_audit_logs_event_type_is_supported"), "audit_logs", type_="check"
    )
    op.create_check_constraint(
        "event_type_is_supported",
        "audit_logs",
        "event_type IN ('login_succeeded', 'password_changed', 'company_selected', "
        "'logout', 'email_verified', 'password_reset')",
    )


def downgrade():
    op.drop_constraint(
        op.f("ck_audit_logs_event_type_is_supported"), "audit_logs", type_="check"
    )
    op.create_check_constraint(
        "event_type_is_supported",
        "audit_logs",
        "event_type IN ('login_succeeded', 'password_changed', 'company_selected', "
        "'logout', 'email_verified')",
    )
    for policy in (
        "password_reset_token_replace",
        "password_reset_token_create",
        "password_reset_token_read",
        "password_reset_token_redeem",
    ):
        op.execute(f"DROP POLICY IF EXISTS {policy} ON password_reset_tokens")
    op.execute("ALTER TABLE password_reset_tokens NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE password_reset_tokens DISABLE ROW LEVEL SECURITY")
    op.execute(
        "REVOKE SELECT, INSERT, UPDATE, DELETE ON password_reset_tokens FROM sales_dash_app"
    )
    op.drop_index(
        "ix_password_reset_tokens_user_created",
        table_name="password_reset_tokens",
    )
    op.drop_table("password_reset_tokens")
