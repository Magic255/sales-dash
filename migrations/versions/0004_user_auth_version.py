"""Add account-wide session revocation version.

Revision ID: 0004_user_auth_version
Revises: 0003_authentication_email_lookup
"""

from alembic import op
import sqlalchemy as sa


revision = "0004_user_auth_version"
down_revision = "0003_authentication_email_lookup"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "users",
        sa.Column("auth_version", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade():
    op.drop_column("users", "auth_version")
