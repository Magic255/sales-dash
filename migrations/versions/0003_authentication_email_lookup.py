"""Allow the restricted app role to look up one exact login email.

Revision ID: 0003_authentication_email_lookup
Revises: 0002_company_access_boundary
"""

from alembic import op  # noqa: I001


revision = "0003_authentication_email_lookup"
down_revision = "0002_company_access_boundary"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        CREATE POLICY users_read_for_login ON users
        FOR SELECT TO sales_dash_app
        USING (
            email = NULLIF(current_setting('app.login_email', true), '')
        )
        """
    )


def downgrade():
    op.execute("DROP POLICY IF EXISTS users_read_for_login ON users")
