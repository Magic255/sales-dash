"""Add controlled, single-use company invitations.

Revision ID: 0009_company_invitations
Revises: 0008_password_reset
"""

# ruff: noqa: I001
from alembic import op
import sqlalchemy as sa


revision = "0009_company_invitations"
down_revision = "0008_password_reset"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "company_invitations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("invited_email", sa.String(length=320), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("invited_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["invited_by_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_company_invitations_token_hash"),
        sa.CheckConstraint(
            "role IN ('manager', 'salesperson', 'viewer')",
            name="role_is_invitable",
        ),
        sa.CheckConstraint(
            "invited_email = lower(trim(invited_email)) AND length(invited_email) > 0",
            name="email_normalized",
        ),
    )
    op.create_index(
        "ix_company_invitations_company_email",
        "company_invitations",
        ["company_id", "invited_email"],
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON company_invitations TO sales_dash_app"
    )
    op.execute("ALTER TABLE company_invitations ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE company_invitations FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY company_invitations_read ON company_invitations
        FOR SELECT TO sales_dash_app
        USING (
            company_id =
                NULLIF(current_setting('app.current_company_id', true), '')::uuid
            OR token_hash =
                NULLIF(current_setting('app.company_invitation_token_hash', true), '')
        )
        """
    )
    op.execute(
        """
        CREATE POLICY company_invitations_create ON company_invitations
        FOR INSERT TO sales_dash_app
        WITH CHECK (
            company_id =
                NULLIF(current_setting('app.current_company_id', true), '')::uuid
        )
        """
    )
    op.execute(
        """
        CREATE POLICY company_invitations_update ON company_invitations
        FOR UPDATE TO sales_dash_app
        USING (
            company_id =
                NULLIF(current_setting('app.current_company_id', true), '')::uuid
            OR token_hash =
                NULLIF(current_setting('app.company_invitation_token_hash', true), '')
        )
        WITH CHECK (
            company_id =
                NULLIF(current_setting('app.current_company_id', true), '')::uuid
            OR token_hash =
                NULLIF(current_setting('app.company_invitation_token_hash', true), '')
        )
        """
    )
    op.execute(
        """
        CREATE POLICY company_invitations_delete ON company_invitations
        FOR DELETE TO sales_dash_app
        USING (
            company_id =
                NULLIF(current_setting('app.current_company_id', true), '')::uuid
        )
        """
    )

    # Membership creation is possible only after the API validates and consumes
    # a matching invitation, then sets this transaction-local company context.
    op.execute("GRANT INSERT ON company_memberships TO sales_dash_app")
    op.execute(
        """
        CREATE POLICY memberships_insert_from_invitation ON company_memberships
        FOR INSERT TO sales_dash_app
        WITH CHECK (
            status = 'active'
            AND user_id =
                NULLIF(current_setting('app.current_user_id', true), '')::uuid
            AND company_id =
                NULLIF(current_setting('app.invitation_company_id', true), '')::uuid
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
        "'logout', 'email_verified', 'password_reset', 'company_invitation_created', "
        "'company_invitation_accepted', 'company_invitation_revoked')",
    )


def downgrade():
    op.drop_constraint(
        op.f("ck_audit_logs_event_type_is_supported"), "audit_logs", type_="check"
    )
    op.create_check_constraint(
        "event_type_is_supported",
        "audit_logs",
        "event_type IN ('login_succeeded', 'password_changed', 'company_selected', "
        "'logout', 'email_verified', 'password_reset')",
    )
    op.execute(
        "DROP POLICY IF EXISTS memberships_insert_from_invitation ON company_memberships"
    )
    op.execute("REVOKE INSERT ON company_memberships FROM sales_dash_app")
    for policy in (
        "company_invitations_delete",
        "company_invitations_update",
        "company_invitations_create",
        "company_invitations_read",
    ):
        op.execute(f"DROP POLICY IF EXISTS {policy} ON company_invitations")
    op.execute("ALTER TABLE company_invitations NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE company_invitations DISABLE ROW LEVEL SECURITY")
    op.execute(
        "REVOKE SELECT, INSERT, UPDATE, DELETE ON company_invitations FROM sales_dash_app"
    )
    op.drop_index(
        "ix_company_invitations_company_email", table_name="company_invitations"
    )
    op.drop_table("company_invitations")
