"""Add company-isolated monthly sales targets.

Revision ID: 0013_monthly_sales_targets
Revises: 0012_team_member_management
"""

from alembic import op

revision = "0013_monthly_sales_targets"
down_revision = "0012_team_member_management"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        CREATE TABLE sales_targets (
            id UUID PRIMARY KEY,
            company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
            period_start DATE NOT NULL,
            target_type VARCHAR(20) NOT NULL,
            salesperson_user_id UUID,
            currency VARCHAR(3) NOT NULL,
            target_amount NUMERIC(14, 2) NOT NULL,
            CONSTRAINT uq_sales_targets_period_owner_currency
                UNIQUE (company_id, period_start, target_type, salesperson_user_id, currency),
            CONSTRAINT fk_sales_targets_salesperson_membership
                FOREIGN KEY (company_id, salesperson_user_id)
                REFERENCES company_memberships(company_id, user_id) ON DELETE CASCADE,
            CONSTRAINT ck_sales_targets_target_type_supported
                CHECK (target_type IN ('company', 'salesperson')),
            CONSTRAINT ck_sales_targets_target_owner_matches_type
                CHECK (
                    (target_type = 'company' AND salesperson_user_id IS NULL)
                    OR (target_type = 'salesperson' AND salesperson_user_id IS NOT NULL)
                ),
            CONSTRAINT ck_sales_targets_target_amount_positive CHECK (target_amount > 0),
            CONSTRAINT ck_sales_targets_currency_iso_code
                CHECK (length(currency) = 3 AND currency = upper(currency))
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_sales_targets_company_period "
        "ON sales_targets (company_id, period_start)"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON sales_targets TO sales_dash_app")
    op.execute("ALTER TABLE sales_targets ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE sales_targets FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY sales_targets_company_isolation ON sales_targets
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


def downgrade():
    op.execute("DROP POLICY IF EXISTS sales_targets_company_isolation ON sales_targets")
    op.execute("ALTER TABLE sales_targets NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE sales_targets DISABLE ROW LEVEL SECURITY")
    op.execute("REVOKE SELECT, INSERT, UPDATE, DELETE ON sales_targets FROM sales_dash_app")
    op.execute("DROP INDEX IF EXISTS ix_sales_targets_company_period")
    op.execute("DROP TABLE sales_targets")
