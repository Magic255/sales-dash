"""Server-side authorization for company-scoped actions.

Always use these guards on tenant API routes. The selected company ID comes from
the signed session, but access is revalidated against the database on every request.
"""
from functools import wraps
from uuid import UUID

from flask import g, jsonify, session

from .extensions import db
from .tenancy import TenantAccessDenied, set_tenant_context


ROLE_PERMISSIONS = {
    "admin": frozenset({
        "view_dashboard", "view_reports", "create_sales", "edit_sales",
        "delete_sales", "manage_products", "manage_team", "manage_company_settings",
    }),
    "manager": frozenset({
        "view_dashboard", "view_reports", "create_sales", "edit_sales",
        "manage_products",
    }),
    "salesperson": frozenset({"view_dashboard", "view_reports", "create_sales"}),
    "viewer": frozenset({"view_dashboard", "view_reports"}),
}


def company_permission_required(permission):
    """Protect a route with a permission granted by the active company role.

    Decorator order: put @login_required outside this decorator so the current
    authenticated user is passed as the first view argument.
    """
    if not isinstance(permission, str) or not permission:
        raise ValueError("A non-empty permission name is required.")

    def decorate(view):
        @wraps(view)
        def wrapped(user, *args, **kwargs):
            company_id = session.get("company_id")
            if not company_id:
                return jsonify({"error": "Select a company before continuing."}), 409

            try:
                membership = set_tenant_context(db.session, user.id, UUID(company_id))
            except (TenantAccessDenied, ValueError, TypeError):
                db.session.rollback()
                session.pop("company_id", None)
                return jsonify({"error": "You do not have access to that company."}), 403

            if permission not in ROLE_PERMISSIONS.get(membership.role, frozenset()):
                return jsonify({"error": "You are not allowed to perform this action."}), 403

            g.company_membership = membership
            return view(user, *args, **kwargs)

        return wrapped

    return decorate
