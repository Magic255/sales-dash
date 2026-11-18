"""Enforce one unconsumed password reset token per account.

Revision ID: 0014_reset_active_unique
Revises: 0013_monthly_sales_targets
"""

# ruff: noqa: I001
from alembic import op
import sqlalchemy as sa


revision = "0014_reset_active_unique"
down_revision = "0013_monthly_sales_targets"
branch_labels = None
depends_on = None


def upgrade():
    # Keep the newest outstanding token if older deployments contain duplicates.
    op.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                row_number() OVER (
                    PARTITION BY user_id
                    ORDER BY created_at DESC, id DESC
                ) AS position
            FROM password_reset_tokens
            WHERE consumed_at IS NULL
        )
        DELETE FROM password_reset_tokens AS tokens
        USING ranked
        WHERE tokens.id = ranked.id
          AND ranked.position > 1
        """
    )
    op.create_index(
        "uq_password_reset_tokens_one_unconsumed_per_user",
        "password_reset_tokens",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("consumed_at IS NULL"),
    )


def downgrade():
    op.drop_index(
        "uq_password_reset_tokens_one_unconsumed_per_user",
        table_name="password_reset_tokens",
    )
