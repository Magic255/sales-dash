"""Enforce at most one unconsumed password reset token per account.

Revision ID: 0013_password_reset_single_active_token
Revises: 0012_team_member_management
"""

# ruff: noqa: I001
from alembic import op
import sqlalchemy as sa


revision = "0013_password_reset_single_active_token"
down_revision = "0012_team_member_management"
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
