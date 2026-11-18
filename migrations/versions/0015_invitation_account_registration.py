"""Allow account creation only through a valid company invitation token.

Revision ID: 0015_invitation_account_registration
Revises: 0014_reset_active_unique
"""

# ruff: noqa: I001
from alembic import op


revision = "0015_invitation_account_registration"
down_revision = "0014_reset_active_unique"
branch_labels = None
depends_on = None


def upgrade():
    # A runtime account can insert a user only when the same transaction has
    # proved possession of a live invitation token for that exact email.
    op.execute("GRANT INSERT ON users TO sales_dash_app")
    op.execute(
        """
        CREATE POLICY users_insert_from_company_invitation ON users
        FOR INSERT TO sales_dash_app
        WITH CHECK (
            email = NULLIF(current_setting('app.login_email', true), '')
            AND email_verified IS TRUE
            AND is_active IS TRUE
            AND password_hash IS NOT NULL
            AND EXISTS (
                SELECT 1
                FROM company_invitations AS invitation
                WHERE invitation.invited_email = users.email
                  AND invitation.token_hash =
                      NULLIF(
                          current_setting('app.company_invitation_token_hash', true),
                          ''
                      )
                  AND invitation.accepted_at IS NULL
                  AND invitation.revoked_at IS NULL
                  AND invitation.expires_at > now()
            )
        )
        """
    )


def downgrade():
    op.execute(
        "DROP POLICY IF EXISTS users_insert_from_company_invitation ON users"
    )
    op.execute("REVOKE INSERT ON users FROM sales_dash_app")
