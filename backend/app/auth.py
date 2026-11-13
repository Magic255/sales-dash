"""Session-based authentication and company selection endpoints."""

from functools import wraps
from uuid import UUID

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from flask import Blueprint, jsonify, request, session
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from . import limiter
from .extensions import db
from .models import CompanyMembership
from .tenancy import TenantAccessDenied, find_login_user, set_tenant_context, set_user_context

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")
password_hasher = PasswordHasher()
# Verify unknown email addresses against a real Argon2 hash too, reducing timing leaks.
_DUMMY_PASSWORD_HASH = password_hasher.hash("not-a-real-sales-dash-password")


def _current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    try:
        return set_user_context(db.session, UUID(user_id))
    except (TenantAccessDenied, ValueError, TypeError):
        session.clear()
        return None


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = _current_user()
        if user is None:
            return jsonify({"error": "Authentication required."}), 401
        return view(user, *args, **kwargs)

    return wrapped


@auth_bp.get("/csrf")
def csrf_token():
    from flask_wtf.csrf import generate_csrf

    return jsonify({"csrf_token": generate_csrf()})


@auth_bp.post("/login")
@limiter.limit("5 per minute; 20 per hour")
def login():
    data = request.get_json(silent=True) or {}
    email = str(data.get("email", "")).strip().lower()
    password = data.get("password", "")
    if (
        not email
        or len(email) > 320
        or not isinstance(password, str)
        or not password
        or len(password) > 1024
    ):
        return jsonify({"error": "Enter your email and password."}), 400

    user = find_login_user(db.session, email)
    stored_hash = user.password_hash if user and user.is_active and user.password_hash else _DUMMY_PASSWORD_HASH
    try:
        password_valid = password_hasher.verify(stored_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        password_valid = False

    if not user or not user.is_active or not password_valid:
        return jsonify({"error": "Email or password is incorrect."}), 401

    user_id = user.id
    try:
        set_user_context(db.session, user_id)
        db.session.commit()
    except TenantAccessDenied:
        db.session.rollback()
        return jsonify({"error": "Unable to sign in. Contact your administrator."}), 401

    session.clear()
    session["user_id"] = str(user_id)
    session.permanent = True
    return jsonify({"authenticated": True})


@auth_bp.get("/me")
def me():
    user = _current_user()
    if user is None:
        return jsonify({"authenticated": False})

    memberships = db.session.scalars(
        select(CompanyMembership)
        .options(joinedload(CompanyMembership.company))
        .where(
            CompanyMembership.user_id == user.id,
            CompanyMembership.status == "active",
        )
        .order_by(CompanyMembership.created_at, CompanyMembership.company_id)
    ).unique().all()

    companies = [
        {
            "id": str(item.company.id),
            "name": item.company.name,
            "role": item.role,
        }
        for item in memberships
        if item.company.is_active
    ]

    selected_company_id = session.get("company_id")
    selected_company = None
    if selected_company_id:
        try:
            membership = set_tenant_context(
                db.session, user.id, UUID(selected_company_id)
            )
            selected_company = {
                "id": str(membership.company_id),
                "name": membership.company.name,
                "role": membership.role,
            }
        except (TenantAccessDenied, ValueError, TypeError):
            session.pop("company_id", None)

    return jsonify(
        {
            "authenticated": True,
            "user": {"email": user.email, "display_name": user.display_name},
            "companies": companies,
            "selected_company": selected_company,
        }
    )


@auth_bp.post("/company")
@login_required
def select_company(user):
    data = request.get_json(silent=True) or {}
    try:
        company_id = UUID(str(data.get("company_id", "")))
        membership = set_tenant_context(db.session, user.id, company_id)
    except (ValueError, TypeError, TenantAccessDenied):
        db.session.rollback()
        return jsonify({"error": "You do not have access to that company."}), 403

    selected_company = {
        "id": str(membership.company_id),
        "name": membership.company.name,
        "role": membership.role,
    }
    db.session.commit()
    session["company_id"] = selected_company["id"]
    return jsonify(
        {
            "selected_company": selected_company,
            }
        }
    )


@auth_bp.post("/logout")
def logout():
    session.clear()
    return jsonify({"authenticated": False})
