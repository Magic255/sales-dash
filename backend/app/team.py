"""Admin-managed, email-bound invitations for existing verified accounts."""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

from flask import Blueprint, current_app, jsonify, request, session
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import IntegrityError

from . import limiter
from .audit import record_audit_event
from .auth import login_required
from .company_invitation import CompanyInvitation
from .extensions import db
from .models import Company, CompanyMembership
from .permissions import company_permission_required
from .tenancy import activate_app_role, find_login_user, set_user_context

team_bp = Blueprint("team", __name__, url_prefix="/api/team")
_INVITABLE_ROLES = frozenset({"manager", "salesperson", "viewer"})


def _invitation_link(token: str) -> str:
    base_url = (current_app.config.get("PUBLIC_BASE_URL") or "").strip().rstrip("/")
    if not base_url or "\r" in base_url or "\n" in base_url:
        raise RuntimeError("Public application URL is not configured.")
    if current_app.config.get("APP_ENV") == "production" and not base_url.startswith("https://"):
        raise RuntimeError("Production invitation links must use HTTPS.")
    return f"{base_url}/#accept_invitation={token}"


@team_bp.get("/invitations")
@login_required
@company_permission_required("manage_team")
def list_company_invitations(user):
    """List pending invitations for the currently selected company."""
    now = datetime.now(timezone.utc)
    items = db.session.scalars(
        select(CompanyInvitation)
        .where(
            CompanyInvitation.accepted_at.is_(None),
            CompanyInvitation.revoked_at.is_(None),
            CompanyInvitation.expires_at > now,
        )
        .order_by(CompanyInvitation.created_at.desc())
        .limit(100)
    ).all()
    return jsonify(
        {
            "items": [
                {
                    "id": str(item.id),
                    "email": item.invited_email,
                    "role": item.role,
                    "expires_at": item.expires_at.isoformat(),
                }
                for item in items
            ]
        }
    )


@team_bp.post("/invitations")
@login_required
@company_permission_required("manage_team")
@limiter.limit("10 per hour")
def create_company_invitation(user):
    """Invite an existing, active, email-verified account into this company."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Enter an email address and role."}), 400
    email = str(data.get("email", "")).strip().lower()
    role = data.get("role")
    if not email or len(email) > 320 or "@" not in email or role not in _INVITABLE_ROLES:
        return jsonify({"error": "Enter a valid email address and an allowed role."}), 400
    if email == user.email:
        return jsonify({"error": "You cannot invite your own account."}), 400

    invited_user = find_login_user(db.session, email)
    if not invited_user or not invited_user.is_active or not invited_user.email_verified:
        return jsonify(
            {
                "message": (
                    "If this is an active, email-verified SALES DASH account, "
                    "an invitation will be sent."
                )
            }
        )

    company_id = UUID(session["company_id"])
    company = db.session.get(Company, company_id)
    if company is None:
        db.session.rollback()
        return jsonify({"error": "The selected company is unavailable."}), 409

    now = datetime.now(timezone.utc)
    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    invitation = CompanyInvitation(
        company_id=company_id,
        invited_email=email,
        role=role,
        token_hash=token_hash,
        invited_by_user_id=user.id,
        expires_at=now + timedelta(days=7),
    )
    try:
        # Only one live invitation per company/email; a resend replaces the old link.
        db.session.execute(
            delete(CompanyInvitation).where(
                CompanyInvitation.company_id == company_id,
                CompanyInvitation.invited_email == email,
                CompanyInvitation.accepted_at.is_(None),
            )
        )
        db.session.add(invitation)
        db.session.commit()
        from .email import send_email

        send_email(
            email,
            f"Invitation to join {company.name} on SALES DASH",
            (
                f"You have been invited to join {company.name} on SALES DASH "
                f"with the {role} role. Sign in using this same email address, "
                "then open this link to accept. The link expires in 7 days and "
                f"can be used once:\n\n{_invitation_link(raw_token)}\n\n"
                "If you were not expecting this invitation, you can ignore this email."
            ),
        )
        record_audit_event(db.session, user.id, "company_invitation_created", company_id)
        db.session.commit()
    except Exception:
        db.session.rollback()
        try:
            db.session.execute(
                delete(CompanyInvitation).where(
                    CompanyInvitation.token_hash == token_hash
                )
            )
            db.session.commit()
        except Exception:
            db.session.rollback()
        current_app.logger.warning("Company invitation delivery failed.")
        return jsonify({"error": "The invitation email could not be sent. Try again later."}), 503

    return jsonify({"message": "Invitation email sent. The link expires in 7 days."}), 201


@team_bp.delete("/invitations/<uuid:invitation_id>")
@login_required
@company_permission_required("manage_team")
def revoke_company_invitation(user, invitation_id):
    """Revoke a pending invitation in the active company."""
    invitation = db.session.scalar(
        select(CompanyInvitation).where(
            CompanyInvitation.id == invitation_id,
            CompanyInvitation.accepted_at.is_(None),
            CompanyInvitation.revoked_at.is_(None),
        )
    )
    if invitation is None:
        return jsonify({"error": "Pending invitation not found."}), 404
    invitation.revoked_at = datetime.now(timezone.utc)
    record_audit_event(
        db.session,
        user.id,
        "company_invitation_revoked",
        invitation.company_id,
    )
    db.session.commit()
    return jsonify({"revoked": True})


@team_bp.post("/invitations/accept")
@login_required
@limiter.limit("10 per hour")
def accept_company_invitation(user):
    """Consume a valid invitation and create the invited account's membership."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}
    raw_token = data.get("token", "")
    if not isinstance(raw_token, str) or not 32 <= len(raw_token) <= 128:
        return jsonify({"error": "This invitation is invalid or has expired."}), 400
    if not user.email_verified:
        return jsonify({"error": "Verify your email before accepting an invitation."}), 403

    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    now = datetime.now(timezone.utc)
    try:
        set_user_context(db.session, user.id)
        activate_app_role(db.session)
        db.session.execute(
            text(
                "SELECT set_config('app.company_invitation_token_hash', :token_hash, true)"
            ),
            {"token_hash": token_hash},
        )
        invitation = db.session.execute(
            update(CompanyInvitation)
            .where(
                CompanyInvitation.token_hash == token_hash,
                CompanyInvitation.invited_email == user.email,
                CompanyInvitation.accepted_at.is_(None),
                CompanyInvitation.revoked_at.is_(None),
                CompanyInvitation.expires_at > now,
            )
            .values(accepted_at=now)
            .returning(CompanyInvitation.company_id, CompanyInvitation.role)
        ).one_or_none()
        if invitation is None:
            db.session.rollback()
            return jsonify({"error": "This invitation is invalid or has expired."}), 400

        company_id, role = invitation
        db.session.execute(
            text("SELECT set_config('app.invitation_company_id', :company_id, true)"),
            {"company_id": str(company_id)},
        )
        db.session.execute(
            text("SELECT set_config('app.current_company_id', :company_id, true)"),
            {"company_id": str(company_id)},
        )
        db.session.add(
            CompanyMembership(
                company_id=company_id,
                user_id=user.id,
                role=role,
                status="active",
            )
        )
        record_audit_event(
            db.session,
            user.id,
            "company_invitation_accepted",
            company_id,
        )
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "This account already has access to that company."}), 409
    except Exception:
        db.session.rollback()
        current_app.logger.warning("Company invitation acceptance failed.")
        return jsonify({"error": "This invitation is invalid or has expired."}), 400

    return jsonify(
        {
            "accepted": True,
            "message": "Invitation accepted. You can now select the company workspace.",
        }
    )
