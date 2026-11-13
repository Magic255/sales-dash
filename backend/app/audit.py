"""Append-only, tenant-scoped security audit events."""

from uuid import UUID

from flask import Blueprint, jsonify, request
from sqlalchemy import select

from .auth import login_required
from .extensions import db
from .models import AuditLog
from .permissions import company_permission_required

audit_bp = Blueprint("audit", __name__, url_prefix="/api")


def record_audit_event(session, actor_user_id: UUID, event_type: str, company_id=None):
    """Queue a minimal allow-listed event in the caller's current transaction."""
    allowed_events = {
        "login_succeeded",
        "password_changed",
        "company_selected",
        "logout",
    }
    if event_type not in allowed_events:
        raise ValueError("Unsupported audit event.")
    session.add(
        AuditLog(
            actor_user_id=actor_user_id,
            company_id=company_id,
            event_type=event_type,
        )
    )


@audit_bp.get("/audit-logs")
@login_required
@company_permission_required("view_audit_logs")
def list_audit_logs(_user):
    """Return a bounded page of events for the currently selected company."""
    try:
        limit = int(request.args.get("limit", "50"))
        
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid audit log pagination."}), 400

    if not 1 <= limit <= 100:
        return jsonify({"error": "Limit must be between 1 and 100."}), 400

    # The permission decorator establishes PostgreSQL tenant context. The
    # selected company ID is read from the authenticated session by the guard.
    from flask import session

    try:
        company_id = UUID(session["company_id"])
    except (KeyError, TypeError, ValueError):
        return jsonify({"error": "Select a company before continuing."}), 409

    query = select(AuditLog).where(AuditLog.company_id == company_id)
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
                    "company_id": str(item.company_id),
                    "occurred_at": item.occurred_at.isoformat(),
                }
                for item in entries
            ],
            "limit": limit,
        }
    )
