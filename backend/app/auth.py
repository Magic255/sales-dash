"""Session-based authentication and company selection endpoints."""

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps
from uuid import UUID, uuid4

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from flask import Blueprint, current_app, jsonify, request, session
from sqlalchemy import select, text
from sqlalchemy.orm import joinedload

from . import limiter
from .extensions import db
from .models import CompanyMembership
from .tenancy import TenantAccessDenied, find_login_user, set_tenant_context, set_user_context

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")
password_hasher = PasswordHasher()
# Verify unknown email addresses against a real Argon2 hash too, reducing timing leaks.
_DUMMY_PASSWORD_HASH = password_hasher.hash("not-a-real-sales-dash-password")


def _login_account_rate_limit_key():
    """Rate-limit each normalized account identifier without storing raw email in Redis."""
    data = request.get_json(silent=True) or {}
    email = str(data.get("email", "")).strip().lower()
    secret = current_app.config["SECRET_KEY"]
    if isinstance(secret, str):
        secret = secret.encode("utf-8")
    digest = hmac.new(secret, email.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"login-account:{digest}"


def _current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    try:
        user = set_user_context(db.session, UUID(user_id))
        if session.get("auth_version") != user.auth_version:
            session.clear()
            return None
        return user
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



def _verification_rate_limit_key():
    """Rate-limit verification requests by a keyed digest, never raw email."""
    data = request.get_json(silent=True) or {}
    email = str(data.get("email", "")).strip().lower()
    secret = current_app.config["SECRET_KEY"]
    if isinstance(secret, str):
        secret = secret.encode("utf-8")
    digest = hmac.new(secret, email.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"email-verification:{digest}"


def _verification_link(token: str) -> str:
    base_url = (current_app.config.get("PUBLIC_BASE_URL") or "").strip().rstrip("/")
    if not base_url or "\r" in base_url or "\n" in base_url:
        raise RuntimeError("Public application URL is not configured.")
    if current_app.config.get("APP_ENV") == "production" and not base_url.startswith("https://"):
        raise RuntimeError("Production email links must use HTTPS.")
    return f"{base_url}/?verify_email={token}"


@auth_bp.post("/verification/resend")
@limiter.limit("3 per hour", key_func=_verification_rate_limit_key)
@limiter.limit("10 per hour")
def resend_verification():
    """Send a new verification link without revealing whether an account exists."""
    data = request.get_json(silent=True) or {}
    email = str(data.get("email", "")).strip().lower()
    if not email or len(email) > 320 or "@" not in email:
        return jsonify({"message": "If the account needs verification, an email will be sent."})

    user = find_login_user(db.session, email)
    if user and user.is_active:
        verified = bool(
            db.session.scalar(
                text("SELECT email_verified FROM users WHERE id = :user_id"),
                {"user_id": str(user.id)},
            )
        )
        if not verified:
            raw_token = secrets.token_urlsafe(32)
            token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
            now = datetime.now(timezone.utc)
            try:
                # A resend invalidates every earlier outstanding link for this account.
                db.session.execute(
                    text("DELETE FROM email_verification_tokens WHERE user_id = :user_id"),
                    {"user_id": str(user.id)},
                )
                db.session.execute(
                    text(
                        "INSERT INTO email_verification_tokens "
                        "(id, user_id, token_hash, expires_at) "
                        "VALUES (:id, :user_id, :token_hash, :expires_at)"
                    ),
                    {
                        "id": str(uuid4()),
                        "user_id": str(user.id),
                        "token_hash": token_hash,
                        "expires_at": now + timedelta(hours=24),
                    },
                )
                db.session.commit()
                from .email import send_email

                link = _verification_link(raw_token)
                send_email(
                    user.email,
                    "Verify your SALES DASH email",
                    "Use this link to verify your SALES DASH email address. "
                    "It expires in 24 hours and can be used once:\n\n"
                    f"{link}\n\n"
                    "If you did not request this, you can ignore this message.",
                )
            except Exception:
                db.session.rollback()
                current_app.logger.warning("Email verification delivery failed.")
    return jsonify({"message": "If the account needs verification, an email will be sent."})


@auth_bp.post("/verification/confirm")
@limiter.limit("10 per hour")
def confirm_email_verification():
    """Consume a valid token once, then mark only its owning account verified."""
    data = request.get_json(silent=True) or {}
    raw_token = data.get("token", "")
    if not isinstance(raw_token, str) or not 32 <= len(raw_token) <= 128:
        return jsonify({"error": "This verification link is invalid or has expired."}), 400

    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    now = datetime.now(timezone.utc)
    try:
        if db.session.get_bind().dialect.name == "postgresql":
            db.session.execute(
                text("SELECT set_config('app.email_verification_token_hash', :token_hash, true)"),
                {"token_hash": token_hash},
            )
        user_id = db.session.execute(
            text(
                "UPDATE email_verification_tokens SET consumed_at = :now "
                "WHERE token_hash = :token_hash AND consumed_at IS NULL "
                "AND expires_at > :now RETURNING user_id"
            ),
            {"token_hash": token_hash, "now": now},
        ).scalar_one_or_none()
        if user_id is None:
            db.session.rollback()
            return jsonify({"error": "This verification link is invalid or has expired."}), 400

        user_id = UUID(str(user_id))
        set_user_context(db.session, user_id)
        db.session.execute(
            text("UPDATE users SET email_verified = TRUE WHERE id = :user_id"),
            {"user_id": str(user_id)},
        )
        from .audit import record_audit_event

        record_audit_event(db.session, user_id, "email_verified")
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.warning("Email verification could not be completed.")
        return jsonify({"error": "This verification link is invalid or has expired."}), 400

    return jsonify({"email_verified": True, "message": "Your email is verified. You can now sign in."})


@auth_bp.post("/login")
@limiter.limit("10 per hour", key_func=_login_account_rate_limit_key)
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
    stored_hash = (
        user.password_hash
        if user and user.is_active and user.password_hash
        else _DUMMY_PASSWORD_HASH
    )
    try:
        password_valid = password_hasher.verify(stored_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        password_valid = False

    email_verified = False
    if user and user.is_active:
        email_verified = bool(
            db.session.scalar(
                text("SELECT email_verified FROM users WHERE id = :user_id"),
                {"user_id": str(user.id)},
            )
        )

    if (
        not user
        or not user.is_active
        or not user.password_hash
        or not password_valid
        or not email_verified
    ):
        return jsonify({"error": "Email or password is incorrect."}), 401

    user_id = user.id
    auth_version = user.auth_version
    try:
        set_user_context(db.session, user_id)
        from .audit import record_audit_event

        record_audit_event(db.session, user_id, "login_succeeded")
        db.session.commit()
    except TenantAccessDenied:
        db.session.rollback()
        return jsonify({"error": "Unable to sign in. Contact your administrator."}), 401

    session.clear()
    session["user_id"] = str(user_id)
    session["auth_version"] = auth_version
    session.permanent = True
    return jsonify({"authenticated": True})


@auth_bp.post("/password")
@login_required
@limiter.limit("5 per hour")
def change_password(user):
    """Change the current password and revoke every existing account session."""
    data = request.get_json(silent=True) or {}
    current_password = data.get("current_password", "")
    new_password = data.get("new_password", "")
    if (
        not isinstance(current_password, str)
        or not current_password
        or len(current_password) > 1024
        or not isinstance(new_password, str)
        or len(new_password) < 12
        or len(new_password) > 1024
    ):
        return (
            jsonify(
                {
                    "error": (
                        "Enter your current password and a new password of at least "
                        "12 characters."
                    )
                }
            ),
            400,
        )

    if not user.password_hash:
        return (
            jsonify(
                {"error": "Complete password setup before changing your password."}
            ),
            403,
        )

    try:
        password_hasher.verify(user.password_hash, current_password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return jsonify({"error": "Current password is incorrect."}), 403

    if user.password_hash:
        try:
            password_hasher.verify(user.password_hash, new_password)
        except VerifyMismatchError:
            pass
        else:
            return (
                jsonify(
                    {"error": "Choose a password different from your current password."}
                ),
                400,
            )

    user.password_hash = password_hasher.hash(new_password)
    user.auth_version += 1
    from .audit import record_audit_event

    record_audit_event(db.session, user.id, "password_changed")
    db.session.commit()
    session.clear()
    return jsonify({"password_changed": True, "authenticated": False})


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
            "user": {"id": str(user.id), "email": user.email, "display_name": user.display_name},
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
    from .audit import record_audit_event

    record_audit_event(db.session, user.id, "company_selected", company_id=company_id)
    db.session.commit()
    session["company_id"] = selected_company["id"]
    return jsonify({"selected_company": selected_company})


@auth_bp.post("/logout")
def logout():
    user = _current_user()
    if user is not None:
        from .audit import record_audit_event

        record_audit_event(db.session, user.id, "logout")
        db.session.commit()
    session.clear()
    return jsonify({"authenticated": False})
