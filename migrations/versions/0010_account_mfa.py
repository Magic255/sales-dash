"""Add optional TOTP MFA credentials and one-time recovery codes.

Revision ID: 0010_account_mfa
Revises: 0009_company_invitations
"""

# ruff: noqa: I001
from alembic import op
import sqlalchemy as sa


revision = "0010_account_mfa"
down_revision = "0009_company_invitations"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "mfa_credentials",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("secret_ciphertext", sa.String(length=255), nullable=False),
        sa.Column("enabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_table(
        "mfa_recovery_codes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "code_hash", name="uq_mfa_recovery_user_hash"),
    )
    op.create_index("ix_mfa_recovery_codes_user_id", "mfa_recovery_codes", ["user_id"])
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON mfa_credentials TO sales_dash_app")
    op.execute("GRANT SELECT, INSERT, DELETE ON mfa_recovery_codes TO sales_dash_app")
    op.execute("ALTER TABLE mfa_credentials ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE mfa_credentials FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY mfa_credentials_read ON mfa_credentials
        FOR SELECT TO sales_dash_app
        USING (
            user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
            OR EXISTS (
                SELECT 1 FROM users
                WHERE users.id = mfa_credentials.user_id
                  AND users.email = NULLIF(current_setting('app.login_email', true), '')
            )
        )
        """
    )
    op.execute(
        """
        CREATE POLICY mfa_credentials_insert ON mfa_credentials
        FOR INSERT TO sales_dash_app
        WITH CHECK (
            user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
        )
        """
    )
    op.execute(
        """
        CREATE POLICY mfa_credentials_update ON mfa_credentials
        FOR UPDATE TO sales_dash_app
        USING (user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid)
        WITH CHECK (user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid)
        """
    )
    op.execute(
        """
        CREATE POLICY mfa_credentials_delete ON mfa_credentials
        FOR DELETE TO sales_dash_app
        USING (user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid)
        """
    )
    op.execute("ALTER TABLE mfa_recovery_codes ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE mfa_recovery_codes FORCE ROW LEVEL SECURITY")
    for action in ("SELECT", "INSERT", "DELETE"):
        if action == "SELECT":
            policy = """
            CREATE POLICY mfa_recovery_codes_read ON mfa_recovery_codes
            FOR SELECT TO sales_dash_app
            USING (user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid)
            """
        elif action == "INSERT":
            policy = """
            CREATE POLICY mfa_recovery_codes_insert ON mfa_recovery_codes
            FOR INSERT TO sales_dash_app
            WITH CHECK (user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid)
            """
        else:
            policy = """
            CREATE POLICY mfa_recovery_codes_delete ON mfa_recovery_codes
            FOR DELETE TO sales_dash_app
            USING (user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid)
            """
        op.execute(policy)

    op.drop_constraint(op.f("ck_audit_logs_event_type_is_supported"), "audit_logs", type_="check")
    op.create_check_constraint(
        "event_type_is_supported",
        "audit_logs",
        "event_type IN ('login_succeeded', 'password_changed', 'company_selected', "
        "'logout', 'email_verified', 'password_reset', 'company_invitation_created', "
        "'company_invitation_accepted', 'company_invitation_revoked', 'mfa_enabled', "
        "'mfa_disabled', 'mfa_recovery_code_used')",
    )


def downgrade():
    op.drop_constraint(op.f("ck_audit_logs_event_type_is_supported"), "audit_logs", type_="check")
    op.create_check_constraint(
        "event_type_is_supported",
        "audit_logs",
        "event_type IN ('login_succeeded', 'password_changed', 'company_selected', "
        "'logout', 'email_verified', 'password_reset', 'company_invitation_created', "
        "'company_invitation_accepted', 'company_invitation_revoked')",
    )
    for policy in (
        "mfa_recovery_codes_delete",
        "mfa_recovery_codes_insert",
        "mfa_recovery_codes_read",
    ):
        op.execute(f"DROP POLICY IF EXISTS {policy} ON mfa_recovery_codes")
    for policy in (
        "mfa_credentials_delete",
        "mfa_credentials_update",
        "mfa_credentials_insert",
        "mfa_credentials_read",
    ):
        op.execute(f"DROP POLICY IF EXISTS {policy} ON mfa_credentials")
    op.execute("ALTER TABLE mfa_recovery_codes NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE mfa_recovery_codes DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE mfa_credentials NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE mfa_credentials DISABLE ROW LEVEL SECURITY")
    op.execute("REVOKE SELECT, INSERT, DELETE ON mfa_recovery_codes FROM sales_dash_app")
    op.execute("REVOKE SELECT, INSERT, UPDATE, DELETE ON mfa_credentials FROM sales_dash_app")
    op.drop_index("ix_mfa_recovery_codes_user_id", table_name="mfa_recovery_codes")
    op.drop_table("mfa_recovery_codes")
    op.drop_table("mfa_credentials")
