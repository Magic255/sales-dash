"""Helpers for establishing a verified company context inside a transaction.

The user_id passed here must come from a future server-verified login session,
never directly from an untrusted request parameter.
"""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session


class TenantAccessDenied(PermissionError):
    """Raised when a user does not have an active membership in a company."""


def set_tenant_context(session: Session, user_id: UUID, company_id: UUID) -> None:
    """Set transaction-local identity and company context after membership verification.

    PostgreSQL RLS policies read these settings. The settings are transaction-local,
    so they disappear automatically when the transaction commits or rolls back.
    """
    session.execute(text("SELECT set_config('app.current_company_id', '', true)"))
    session.execute(
        text("SELECT set_config('app.current_user_id', :user_id, true)"),
        {"user_id": str(user_id)},
    )

    is_active_member = session.execute(
        text(
            """
            SELECT EXISTS (
                SELECT 1
                FROM company_memberships AS membership
                JOIN users AS account ON account.id = membership.user_id
                WHERE membership.user_id = :user_id
                  AND membership.company_id = :company_id
                  AND membership.status = 'active'
                  AND account.is_active = TRUE
            )
            """
        ),
        {"user_id": str(user_id), "company_id": str(company_id)},
    ).scalar_one()

    if not is_active_member:
        raise TenantAccessDenied("No active user membership for the selected company.")

    session.execute(
        text("SELECT set_config('app.current_company_id', :company_id, true)"),
        {"company_id": str(company_id)},
    )
