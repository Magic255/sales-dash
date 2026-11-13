"""Add fail-closed row-level security for company access.

Revision ID: 0002_company_access_boundary
Revises: 0001_multi_company_core
"""

from alembic import op  # noqa: I001


revision = "0002_company_access_boundary"
down_revision = "0001_multi_company_core"
branch_labels = None
depends_on = None


def upgrade():
    # A NOLOGIN permission group. The production login role must be granted this
    # role; it must not be a superuser, table owner, or BYPASSRLS role.
    op.execute(
        """
        DO $$
        BEGIN
            CREATE ROLE sales_dash_app NOLOGIN;
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END
        $$;
        """
    )
    op.execute(
        """
        GRANT SELECT ON users, companies, company_memberships TO sales_dash_app;
        CREATE INDEX ix_company_memberships_user_id
            ON company_memberships (user_id);
        """
    )

    # No context means no rows. FORCE also applies policies to the table owner;
    # PostgreSQL superusers still bypass RLS and must never be used by the app.
    for table in ("users", "companies", "company_memberships"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")

    op.execute(
        """
        CREATE POLICY users_read_self ON users
        FOR SELECT TO sales_dash_app
        USING (
            id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
        );

        CREATE POLICY memberships_read_self ON company_memberships
        FOR SELECT TO sales_dash_app
        USING (
            user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
        );

        CREATE POLICY companies_read_active_membership ON companies
        FOR SELECT TO sales_dash_app
        USING (
            EXISTS (
                SELECT 1
                FROM company_memberships AS membership
                WHERE membership.company_id = companies.id
                  AND membership.user_id =
                      NULLIF(current_setting('app.current_user_id', true), '')::uuid
                  AND membership.status = 'active'
            )
        );
        """
    )


def downgrade():
    op.execute(
        """
        DROP POLICY IF EXISTS companies_read_active_membership ON companies;
        DROP POLICY IF EXISTS memberships_read_self ON company_memberships;
        DROP POLICY IF EXISTS users_read_self ON users;
        """
    )
    for table in ("users", "companies", "company_memberships"):
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    op.execute("DROP INDEX IF EXISTS ix_company_memberships_user_id")
    op.execute("REVOKE SELECT ON users, companies, company_memberships FROM sales_dash_app")
    # Keep the NOLOGIN role: it may already be assigned to a deployment login role.
    # Removing it automatically would make rollback unsafe.
