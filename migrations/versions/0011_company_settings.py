"""Allow administrator-only company display-name updates.

Revision ID: 0011_company_settings
Revises: 0010_account_mfa
"""

# ruff: noqa: I001
from alembic import op


revision = "0011_company_settings"
down_revision = "0010_account_mfa"
branch_labels = None
depends_on = None


def upgrade():
    # The runtime role may update only the display name. The endpoint applies
    # the company-admin permission check, while RLS independently limits the
    # row to an active administrator in the transaction's selected company.
    op.execute("GRANT UPDATE (name, updated_at) ON companies TO sales_dash_app")
    op.execute(
        """
        CREATE POLICY companies_update_admin ON companies
        FOR UPDATE TO sales_dash_app
        USING (
            id = NULLIF(current_setting('app.current_company_id', true), '')::uuid
            AND EXISTS (
                SELECT 1
                FROM company_memberships AS membership
                WHERE membership.company_id = companies.id
                  AND membership.user_id =
                      NULLIF(current_setting('app.current_user_id', true), '')::uuid
                  AND membership.status = 'active'
                  AND membership.role = 'admin'
            )
        )
        WITH CHECK (
            id = NULLIF(current_setting('app.current_company_id', true), '')::uuid
            AND EXISTS (
                SELECT 1
                FROM company_memberships AS membership
                WHERE membership.company_id = companies.id
                  AND membership.user_id =
                      NULLIF(current_setting('app.current_user_id', true), '')::uuid
                  AND membership.status = 'active'
                  AND membership.role = 'admin'
            )
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
        "'mfa_disabled', 'mfa_recovery_code_used', 'company_settings_updated')",
    )


def downgrade():
    op.drop_constraint(op.f("ck_audit_logs_event_type_is_supported"), "audit_logs", type_="check")
    op.create_check_constraint(
        "event_type_is_supported",
        "audit_logs",
        "event_type IN ('login_succeeded', 'password_changed', 'company_selected', "
        "'logout', 'email_verified', 'password_reset', 'company_invitation_created', "
        "'company_invitation_accepted', 'company_invitation_revoked', 'mfa_enabled', "
        "'mfa_disabled', 'mfa_recovery_code_used')",
    )
    op.execute("DROP POLICY IF EXISTS companies_update_admin ON companies")
    op.execute("REVOKE UPDATE (name, updated_at) ON companies FROM sales_dash_app")
