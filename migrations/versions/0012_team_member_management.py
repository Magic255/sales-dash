"""Allow company administrators to manage non-admin memberships.

Revision ID: 0012_team_member_management
Revises: 0011_company_settings
"""

# ruff: noqa: I001
from alembic import op


revision = "0012_team_member_management"
down_revision = "0011_company_settings"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        CREATE POLICY memberships_read_company ON company_memberships
        FOR SELECT TO sales_dash_app
        USING (
            company_id = NULLIF(current_setting('app.current_company_id', true), '')::uuid
        )
        """
    )
    op.execute(
        """
        CREATE POLICY users_read_company_members ON users
        FOR SELECT TO sales_dash_app
        USING (
            EXISTS (
                SELECT 1
                FROM company_memberships AS membership
                WHERE membership.company_id =
                    NULLIF(current_setting('app.current_company_id', true), '')::uuid
                  AND membership.user_id = users.id
            )
        )
        """
    )
    op.execute("GRANT UPDATE (role, status) ON company_memberships TO sales_dash_app")
    op.execute(
        """
        CREATE POLICY memberships_update_admin ON company_memberships
        FOR UPDATE TO sales_dash_app
        USING (
            company_id = NULLIF(current_setting('app.current_company_id', true), '')::uuid
            AND NULLIF(current_setting('app.current_company_role', true), '') = 'admin'
            AND user_id <>
                NULLIF(current_setting('app.current_user_id', true), '')::uuid
            AND role IN ('manager', 'salesperson', 'viewer')
            AND status IN ('active', 'suspended')
        )
        WITH CHECK (
            company_id = NULLIF(current_setting('app.current_company_id', true), '')::uuid
            AND NULLIF(current_setting('app.current_company_role', true), '') = 'admin'
            AND user_id <>
                NULLIF(current_setting('app.current_user_id', true), '')::uuid
            AND role IN ('manager', 'salesperson', 'viewer')
            AND status IN ('active', 'suspended')
        )
        """
    )

    op.drop_constraint(op.f("ck_audit_logs_event_type_is_supported"), "audit_logs", type_="check")
    op.create_check_constraint(
        "event_type_is_supported",
        "audit_logs",
        "event_type IN ('login_succeeded', 'password_changed', 'company_selected', "
        "'logout', 'email_verified', 'password_reset', 'company_invitation_created', "
        "'company_invitation_accepted', 'company_invitation_revoked', 'mfa_enabled', "
        "'mfa_disabled', 'mfa_recovery_code_used', 'company_settings_updated', "
        "'team_member_role_changed', 'team_member_suspended', 'team_member_reactivated')",
    )


def downgrade():
    op.drop_constraint(op.f("ck_audit_logs_event_type_is_supported"), "audit_logs", type_="check")
    op.create_check_constraint(
        "event_type_is_supported",
        "audit_logs",
        "event_type IN ('login_succeeded', 'password_changed', 'company_selected', "
        "'logout', 'email_verified', 'password_reset', 'company_invitation_created', "
        "'company_invitation_accepted', 'company_invitation_revoked', 'mfa_enabled', "
        "'mfa_disabled', 'mfa_recovery_code_used', 'company_settings_updated')",
    )
    op.execute("DROP POLICY IF EXISTS memberships_update_admin ON company_memberships")
    op.execute("DROP POLICY IF EXISTS users_read_company_members ON users")
    op.execute("DROP POLICY IF EXISTS memberships_read_company ON company_memberships")
    op.execute("REVOKE UPDATE (role, status) ON company_memberships FROM sales_dash_app")
