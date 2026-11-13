"""Fail-closed helpers for database-backed user and tenant context."""

from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .models import Company, CompanyMembership, User


class TenantAccessDenied(PermissionError):
    """Raised when a user does not have an active membership in a company."""


def activate_app_role(session: Session) -> None:
    """Switch the current PostgreSQL transaction to the restricted application role."""
    if session.get_bind().dialect.name == "postgresql":
        session.execute(text("SET LOCAL ROLE sales_dash_app"))


def find_login_user(session: Session, email: str) -> User | None:
    """Look up exactly one normalized email using the dedicated RLS login policy."""
    activate_app_role(session)
    if session.get_bind().dialect.name == "postgresql":
        session.execute(
            text("SELECT set_config('app.login_email', :email, true)"),
            {"email": email.strip().lower()},
        )
    return session.scalar(select(User).where(User.email == email.strip().lower()))


def set_user_context(session: Session, user_id: UUID) -> User:
    """Set a verified global user identity for this transaction."""
    activate_app_role(session)
    if session.get_bind().dialect.name == "postgresql":
        session.execute(text("SELECT set_config('app.current_company_id', '', true)"))
        session.execute(text("SELECT set_config('app.login_email', '', true)"))
        session.execute(
            text("SELECT set_config('app.current_user_id', :user_id, true)"),
            {"user_id": str(user_id)},
        )

    # Refresh from the database even if this ORM session already has the user
    # cached. Account deactivation and auth-version changes must take effect now.
    user = session.scalar(
        select(User)
        .where(User.id == user_id, User.is_active.is_(True))
        .execution_options(populate_existing=True)
    )
    if user is None:
        raise TenantAccessDenied("The user account is not active.")
    return user


def set_tenant_context(
    session: Session, user_id: UUID, company_id: UUID
) -> CompanyMembership:
    """Set a selected company only after checking active user and membership."""
    set_user_context(session, user_id)
    # Refresh membership role/status on every protected request so a role change
    # or suspension cannot be hidden by a stale SQLAlchemy identity-map entry.
    membership = session.scalar(
        select(CompanyMembership)
        .join(Company, Company.id == CompanyMembership.company_id)
        .where(
            CompanyMembership.user_id == user_id,
            CompanyMembership.company_id == company_id,
            CompanyMembership.status == "active",
            Company.is_active.is_(True),
        )
        .execution_options(populate_existing=True)
    )
    if membership is None:
        raise TenantAccessDenied("No active user membership for the selected company.")

    if session.get_bind().dialect.name == "postgresql":
        session.execute(
            text("SELECT set_config('app.current_company_id', :company_id, true)"),
            {"company_id": str(company_id)},
        )
    return membership
