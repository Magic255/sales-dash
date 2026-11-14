"""Company settings available only to company administrators."""

from flask import Blueprint, jsonify, request, session
from uuid import UUID

from .audit import record_audit_event
from .auth import login_required
from .extensions import db
from .models import Company
from .permissions import company_permission_required

company_settings_bp = Blueprint(
    "company_settings", __name__, url_prefix="/api/company/settings"
)


@company_settings_bp.get("")
@login_required
@company_permission_required("manage_company_settings")
def get_company_settings(_user):
    """Return the active company's editable settings."""
    company_id = UUID(session["company_id"])
    company = db.session.get(Company, company_id)
    if company is None:
        return jsonify({"error": "The selected company is unavailable."}), 404
    return jsonify({"item": {"id": str(company.id), "name": company.name, "slug": company.slug}})


@company_settings_bp.patch("")
@login_required
@company_permission_required("manage_company_settings")
def update_company_settings(user):
    """Update the company display name without changing its stable slug."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or set(data) != {"name"}:
        return jsonify({"error": "Provide a company name."}), 400
    raw_name = data.get("name")
    if not isinstance(raw_name, str):
        return jsonify({"error": "Company name must be text."}), 400
    name = raw_name.strip()
    if not name or len(name) > 160:
        return jsonify({"error": "Company name must contain 1 to 160 characters."}), 400

    company_id = UUID(session["company_id"])
    company = db.session.get(Company, company_id)
    if company is None:
        return jsonify({"error": "The selected company is unavailable."}), 404
    if company.name != name:
        company.name = name
        record_audit_event(db.session, user.id, "company_settings_updated", company_id)
        db.session.commit()
    return jsonify({"item": {"id": str(company.id), "name": company.name, "slug": company.slug}})
