"""Add email verification state and restricted single-use tokens.

Revision ID: 0007_email_verification
Revises: 0006_sales_domain
"""


# ruff: noqa: I001
from alembic import op
import sqlalchemy as sa


revision = "0007_email_verification"
down_revision = "0006_sales_domain"
branch_labels = None
depends_on = None


def upgrade():
    # Existing provisioned accounts remain usable. New accounts must verify.
    op.add_column(
        "users",
        sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.alter_column("users", "email_verified", server_default=sa.false())

    op.execute("GRANT UPDATE (email_verified) ON users TO sales_dash_app")
    op.execute(
        """
        CREATE POLICY users_verify_own_email ON users
        FOR UPDATE TO sales_dash_app
        USING (
            id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
        )
        WITH CHECK (
            id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
        )
        """
    )

    op.create_table(
        "email_verification_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_email_verification_tokens_token_hash"),
    )
    op.create_index(
        "ix_email_verification_tokens_user_created",
        "email_verification_tokens",
        ["user_id", "created_at"],
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON email_verification_tokens TO sales_dash_app"
    )
    op.execute("ALTER TABLE email_verification_tokens ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE email_verification_tokens FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY email_verification_token_read ON email_verification_tokens
        FOR SELECT TO sales_dash_app
        USING (
            token_hash =
                NULLIF(current_setting('app.email_verification_token_hash', true), '')
            OR EXISTS (
                SELECT 1 FROM users
                WHERE users.id = email_verification_tokens.user_id
                  AND users.email =
                      NULLIF(current_setting('app.login_email', true), '')
            )
        )
        """
    )
    op.execute(
        """
        CREATE POLICY email_verification_token_redeem ON email_verification_tokens
        FOR UPDATE TO sales_dash_app
        USING (
            token_hash =
                NULLIF(current_setting('app.email_verification_token_hash', true), '')
        )
        WITH CHECK (
            token_hash =
                NULLIF(current_setting('app.email_verification_token_hash', true), '')
        )
        """
    )
    op.execute(
        """
        CREATE POLICY email_verification_token_create ON email_verification_tokens
        FOR INSERT TO sales_dash_app
        WITH CHECK (
            EXISTS (
                SELECT 1 FROM users
                WHERE users.id = email_verification_tokens.user_id
                  AND users.email =
                      NULLIF(current_setting('app.login_email', true), '')
            )
        )
        """
    )
    op.execute(
        """
        CREATE POLICY email_verification_token_replace ON email_verification_tokens
        FOR DELETE TO sales_dash_app
        USING (
            EXISTS (
                SELECT 1 FROM users
                WHERE users.id = email_verification_tokens.user_id
                  AND users.email =
                      NULLIF(current_setting('app.login_email', true), '')
            )
        )
        """
    )

    op.drop_constraint(
        "ck_audit_logs_event_type_is_supported", "audit_logs", type_="check"
    )
    op.create_check_constraint(
        "event_type_is_supported",
        "audit_logs",
        "event_type IN ('login_succeeded', 'password_changed', 'company_selected', "
        "'logout', 'email_verified')",
    )


def downgrade():
    op.drop_constraint(
        "ck_audit_logs_event_type_is_supported", "audit_logs", type_="check"
    )
    op.create_check_constraint(
        "event_type_is_supported",
        "audit_logs",
        "event_type IN ('login_succeeded', 'password_changed', 'company_selected', 'logout')",
    )
    for policy in (
        "email_verification_token_replace",
        "email_verification_token_create",
        "email_verification_token_read",
        "email_verification_token_redeem",
    ):
        op.execute(f"DROP POLICY IF EXISTS {policy} ON email_verification_tokens")
    op.execute("ALTER TABLE email_verification_tokens NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE email_verification_tokens DISABLE ROW LEVEL SECURITY")
    op.execute(
        "REVOKE SELECT, INSERT, UPDATE, DELETE ON email_verification_tokens FROM sales_dash_app"
    )
    op.drop_index(
        "ix_email_verification_tokens_user_created",
        table_name="email_verification_tokens",
    )
    op.drop_table("email_verification_tokens")
    op.execute("DROP POLICY IF EXISTS users_verify_own_email ON users")
    op.execute("REVOKE UPDATE (email_verified) ON users FROM sales_dash_app")
    op.drop_column("users", "email_verified")
