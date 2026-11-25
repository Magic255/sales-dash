"""Company settings available only to company administrators."""

from decimal import Decimal, InvalidOperation
from uuid import UUID

from flask import Blueprint, jsonify, request, session

from .audit import record_audit_event
from .auth import login_required
from .extensions import db
from .models import Company
from .permissions import company_permission_required

company_settings_bp = Blueprint(
    "company_settings", __name__, url_prefix="/api/company/settings"
)


def _settings_json(company):
    return {
        "id": str(company.id),
        "name": company.name,
        "slug": company.slug,
        "discount_limits": {
            "salesperson_percent": str(company.salesperson_discount_limit),
            "manager_percent": str(company.manager_discount_limit),
        },
    }


@company_settings_bp.get("")
@login_required
@company_permission_required("manage_company_settings")
def get_company_settings(_user):
    """Return the active company's editable settings."""
    company = db.session.get(Company, UUID(session["company_id"]))
    if company is None:
        return jsonify({"error": "The selected company is unavailable."}), 404
    return jsonify({"item": _settings_json(company)})


@company_settings_bp.patch("")
@login_required
@company_permission_required("manage_company_settings")
def update_company_settings(user):
    """Update company display name and role-based discount ceilings."""
    data = request.get_json(silent=True)
    allowed = {"name", "salesperson_discount_limit", "manager_discount_limit"}
    if not isinstance(data, dict) or not data or set(data) - allowed:
        return jsonify({"error": "Provide valid company settings."}), 400

    company = db.session.get(Company, UUID(session["company_id"]))
    if company is None:
        return jsonify({"error": "The selected company is unavailable."}), 404

    old_values = {
        "name": company.name,
        "salesperson_discount_limit": str(company.salesperson_discount_limit),
        "manager_discount_limit": str(company.manager_discount_limit),
    }
    try:
        if "name" in data:
            raw_name = data["name"]
            if not isinstance(raw_name, str):
                raise ValueError
            name = raw_name.strip()
            if not name or len(name) > 160:
                raise ValueError
            company.name = name

        for field in ("salesperson_discount_limit", "manager_discount_limit"):
            if field not in data:
                continue
            raw = data[field]
            if isinstance(raw, bool) or raw is None:
                raise ValueError
            try:
                value = Decimal(str(raw))
            except (InvalidOperation, ValueError):
                raise ValueError from None
            if not value.is_finite() or value < 0 or value > 100:
                raise ValueError
            company_value = value.quantize(Decimal("0.01"))
            setattr(company, field, company_value)
    except (ValueError, TypeError):
        db.session.rollback()
        return jsonify({"error": "Use a company name and discount limits from 0 to 100 percent."}), 400

    new_values = {
        "name": company.name,
        "salesperson_discount_limit": str(company.salesperson_discount_limit),
        "manager_discount_limit": str(company.manager_discount_limit),
    }
    if old_values != new_values:
        if old_values["name"] != new_values["name"]:
            record_audit_event(
                db.session, user.id, "company_settings_updated", company.id,
                {"old": old_values["name"], "new": new_values["name"]},
            )
        if any(old_values[key] != new_values[key] for key in (
            "salesperson_discount_limit", "manager_discount_limit"
        )):
            record_audit_event(
                db.session, user.id, "discount_limits_updated", company.id,
                {
                    "old": {
                        key: old_values[key] for key in (
                            "salesperson_discount_limit", "manager_discount_limit"
                        )
                    },
                    "new": {
                        key: new_values[key] for key in (
                            "salesperson_discount_limit", "manager_discount_limit"
                        )
                    },
                },
            )
        db.session.commit()

    return jsonify({"item": _settings_json(company)})
