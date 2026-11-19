"""Permit only the protected table owner to run operator provisioning.

Revision ID: 0016_operator_provisioning_rls
Revises: 0015_invite_account
"""

# ruff: noqa: I001
from alembic import op


revision = "0016_operator_provisioning_rls"
down_revision = "0015_invite_account"
branch_labels = None
depends_on = None


def upgrade():
    # FORCE ROW LEVEL SECURITY also applies to table owners. Operator commands
    # use ADMIN_DATABASE_URL, never the web runtime login. These narrowly scoped
    # policies let the current owner of each provisioning table administer it,
    # while the sales_dash_app role remains subject to tenant policies because
    # current_user becomes sales_dash_app after SET LOCAL ROLE.
    for table in ("users", "companies", "company_memberships"):
        owner_check = (
            "current_user = ("
            "SELECT pg_catalog.pg_get_userbyid(relowner) "
            "FROM pg_catalog.pg_class "
            f"WHERE oid = '{table}'::regclass"
            ")"
        )
        op.execute(
            f"""
            CREATE POLICY {table}_operator_owner_access ON {table}
            FOR ALL TO PUBLIC
            USING ({owner_check})
            WITH CHECK ({owner_check})
            """
        )


def downgrade():
    for table in ("company_memberships", "companies", "users"):
        op.execute(
            f"DROP POLICY IF EXISTS {table}_operator_owner_access ON {table}"
        )
