"""Append-only, tenant-scoped security audit events."""

from uuid import UUID

from flask import Blueprint, jsonify, request, session
from sqlalchemy import and_, or_, select

from .auth import login_required
from .extensions import db
from .models import AuditLog
from .permissions import company_permission_required

audit_bp = Blueprint("audit", __name__, url_prefix="/api")


def record_audit_event(
    session, actor_user_id: UUID, event_type: str, company_id=None, details=None
):
    """Queue a minimal allow-listed event in the caller's current transaction."""
    allowed_events = {
        "login_succeeded",
        "password_changed",
        "company_selected",
        "logout",
        "email_verified",
        "password_reset",
        "company_invitation_created",
        "company_invitation_accepted",
        "company_invitation_revoked",
        "mfa_enabled",
        "mfa_disabled",
        "mfa_recovery_code_used",
        "company_settings_updated",
        "team_member_role_changed",
        "team_member_suspended",
        "team_member_reactivated",
        "product_created",
        "product_updated",
        "discount_limits_updated",
        "discount_approval_requested",
        "discount_approval_decided",
        "price_floor_override",
        "discount_applied",
        "product_compliance_verified",
        "product_compliance_rejected",
        "product_compliance_recalled",
        "product_compliance_exception",
        "product_compliance_policy_updated",
        "product_compliance_evidence_uploaded",
        "product_compliance_evidence_downloaded",
        "product_compliance_not_required_release",
        "supplier_created",
        "supplier_approved",
        "supplier_restricted",
        "supplier_suspended",
        "supplier_rejected",
        "supplier_re_review_required",
        "supplier_document_uploaded",
        "supplier_document_rejected",
        "supplier_document_downloaded",
        "purchase_order_created",
        "purchase_order_receipt_recorded",
        "supplier_invoice_recorded",
        "supplier_invoice_matched",
        "expense_created",
        "expense_voided",
    }
    if event_type not in allowed_events:
        raise ValueError("Unsupported audit event.")
    session.add(
        AuditLog(
            actor_user_id=actor_user_id,
            company_id=company_id,
            event_type=event_type,
            details=details,
        )
    )


@audit_bp.get("/audit-logs")
@login_required
@company_permission_required("view_audit_logs")
def list_audit_logs(user):
    """Return bounded company events and the signed-in admin's own account events."""
    try:
        limit = int(request.args.get("limit", "50"))
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid audit log pagination."}), 400

    if not 1 <= limit <= 100:
        return jsonify({"error": "Limit must be between 1 and 100."}), 400

    # The permission decorator establishes PostgreSQL tenant context. The
    # selected company ID is read from the authenticated session by the guard.
    try:
        company_id = UUID(session["company_id"])
    except (KeyError, TypeError, ValueError):
        return jsonify({"error": "Select a company before continuing."}), 409

    query = select(AuditLog).where(
        or_(
            AuditLog.company_id == company_id,
            and_(AuditLog.company_id.is_(None), AuditLog.actor_user_id == user.id),
        )
    )
    entries = db.session.scalars(
        query.order_by(AuditLog.occurred_at.desc(), AuditLog.id.desc()).limit(limit)
    ).all()
    return jsonify(
        {
            "items": [
                {
                    "id": str(item.id),
                    "event_type": item.event_type,
                    "actor_user_id": str(item.actor_user_id) if item.actor_user_id else None,
                    "company_id": str(item.company_id) if item.company_id else None,
                    "occurred_at": item.occurred_at.isoformat(),
                    "details": item.details,
                }
                for item in entries
            ],
            "limit": limit,
        }
    )
