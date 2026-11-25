"""Add company discount limits and tenant-isolated approval requests.

Revision ID: 0018_discount_approvals
Revises: 0017_product_price_audit
"""

# ruff: noqa: I001
from alembic import op
import sqlalchemy as sa


revision = "0018_discount_approvals"
down_revision = "0017_product_price_audit"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "companies",
        sa.Column(
            "salesperson_discount_limit", sa.Numeric(5, 2),
            nullable=False, server_default="5.00",
        ),
    )
    op.add_column(
        "companies",
        sa.Column(
            "manager_discount_limit", sa.Numeric(5, 2),
            nullable=False, server_default="15.00",
        ),
    )
    op.create_check_constraint(
        "salesperson_discount_limit_range", "companies",
        "salesperson_discount_limit >= 0 AND salesperson_discount_limit <= 100",
    )
    op.create_check_constraint(
        "manager_discount_limit_range", "companies",
        "manager_discount_limit >= 0 AND manager_discount_limit <= 100",
    )
    op.execute(
        "GRANT UPDATE (salesperson_discount_limit, manager_discount_limit) "
        "ON companies TO sales_dash_app"
    )

    op.execute(
        """
        CREATE TABLE discount_approval_requests (
            id UUID PRIMARY KEY,
            company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
            sale_id UUID NOT NULL,
            requested_by_user_id UUID NOT NULL,
            approver_user_id UUID,
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            requested_discount_percent NUMERIC(5, 2) NOT NULL,
            reason VARCHAR(1000) NOT NULL,
            decision_reason VARCHAR(1000),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            decided_at TIMESTAMPTZ,
            CONSTRAINT ck_discount_approval_requests_status_is_supported
                CHECK (status IN ('pending', 'approved', 'rejected', 'superseded')),
            CONSTRAINT ck_discount_approval_requests_discount_percent_range
                CHECK (requested_discount_percent > 0 AND requested_discount_percent <= 100),
            CONSTRAINT ck_discount_approval_requests_reason_not_empty
                CHECK (length(trim(reason)) > 0),
            CONSTRAINT fk_discount_approval_sale_same_company
                FOREIGN KEY (company_id, sale_id)
                REFERENCES sales(company_id, id) ON DELETE CASCADE,
            CONSTRAINT fk_discount_approval_requester_membership
                FOREIGN KEY (company_id, requested_by_user_id)
                REFERENCES company_memberships(company_id, user_id) ON DELETE NO ACTION,
            CONSTRAINT fk_discount_approval_approver_membership
                FOREIGN KEY (company_id, approver_user_id)
                REFERENCES company_memberships(company_id, user_id) ON DELETE NO ACTION
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_discount_approvals_company_status "
        "ON discount_approval_requests (company_id, status, created_at)"
    )
    op.execute(
        "CREATE INDEX ix_discount_approvals_sale_created "
        "ON discount_approval_requests (company_id, sale_id, created_at)"
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON discount_approval_requests TO sales_dash_app"
    )
    op.execute("ALTER TABLE discount_approval_requests ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE discount_approval_requests FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY discount_approval_requests_company_isolation
        ON discount_approval_requests
        FOR ALL TO sales_dash_app
        USING (
            company_id =
            NULLIF(current_setting('app.current_company_id', true), '')::uuid
        )
        WITH CHECK (
            company_id =
            NULLIF(current_setting('app.current_company_id', true), '')::uuid
        )
        """
    )

    op.drop_constraint("event_type_is_supported", "audit_logs", type_="check")
    op.create_check_constraint(
        "event_type_is_supported",
        "audit_logs",
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


def downgrade():
    op.drop_constraint("event_type_is_supported", "audit_logs", type_="check")
    op.create_check_constraint(
        "event_type_is_supported",
        "audit_logs",
        "event_type IN ('login_succeeded', 'password_changed', "
        "'company_selected', 'logout', 'email_verified', 'password_reset', "
        "'company_invitation_created', 'company_invitation_accepted', "
        "'company_invitation_revoked', 'mfa_enabled', 'mfa_disabled', "
        "'mfa_recovery_code_used', 'company_settings_updated', "
        "'team_member_role_changed', 'team_member_suspended', "
        "'team_member_reactivated', 'product_created', 'product_updated')",
    )
    op.execute(
        "DROP POLICY IF EXISTS discount_approval_requests_company_isolation "
        "ON discount_approval_requests"
    )
    op.execute("ALTER TABLE discount_approval_requests NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE discount_approval_requests DISABLE ROW LEVEL SECURITY")
    op.execute("REVOKE SELECT, INSERT, UPDATE ON discount_approval_requests FROM sales_dash_app")
    op.execute("DROP TABLE discount_approval_requests")
    op.execute(
        "REVOKE UPDATE (salesperson_discount_limit, manager_discount_limit) "
        "ON companies FROM sales_dash_app"
    )
    op.drop_constraint("manager_discount_limit_range", "companies", type_="check")
    op.drop_constraint("salesperson_discount_limit_range", "companies", type_="check")
    op.drop_column("companies", "manager_discount_limit")
    op.drop_column("companies", "salesperson_discount_limit")
