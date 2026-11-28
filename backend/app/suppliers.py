"""Company-scoped supplier onboarding and independent approval APIs."""

from datetime import date, datetime, timezone
from uuid import UUID

from flask import Blueprint, jsonify, request, session
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .audit import record_audit_event
from .auth import login_required
from .extensions import db
from .models import Supplier
from .permissions import company_permission_required

suppliers_bp = Blueprint("suppliers", __name__, url_prefix="/api")


def _company_id():
    return UUID(session["company_id"])


def _json_object():
    value = request.get_json(silent=True)
    return value if isinstance(value, dict) else None


def _text(data, key, maximum, *, required=False, lower=False):
    value = data.get(key)
    if value is None:
        if required:
            raise ValueError(f"{key.replace('_', ' ').capitalize()} is required.")
        return None
    if not isinstance(value, str):
        raise ValueError(f"{key.replace('_', ' ').capitalize()} must be text.")
    value = value.strip()
    if required and not value:
        raise ValueError(f"{key.replace('_', ' ').capitalize()} is required.")
    if len(value) > maximum:
        raise ValueError(f"{key.replace('_', ' ').capitalize()} is too long.")
    return value.lower() if lower and value else value


def _country(value):
    if not isinstance(value, str):
        raise ValueError("Country must be a two-letter ISO country code.")
    value = value.strip().upper()
    if len(value) != 2 or not value.isascii() or not value.isalpha():
        raise ValueError("Country must be a two-letter ISO country code.")
    return value


def _string_list(value, field, *, upper=False, lower=False):
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 100:
        raise ValueError(f"{field} must be a list of at most 100 text values.")
    result = []
    for item in value:
        if not isinstance(item, str) or not item.strip() or len(item.strip()) > 100:
            raise ValueError(f"{field} contains an invalid value.")
        item = item.strip()
        result.append(item.upper() if upper else item.lower() if lower else item)
    if len(set(result)) != len(result):
        raise ValueError(f"{field} must not contain duplicates.")
    return result


def _optional_date(value, field):
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must use YYYY-MM-DD.")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{field} must use YYYY-MM-DD.") from None


def _effective_status(supplier):
    if supplier.status == "approved" and supplier.licence_valid_until:
        if supplier.licence_valid_until < date.today():
            return "expired"
    return supplier.status


def _supplier_json(supplier):
    return {
        "id": str(supplier.id),
        "legal_name": supplier.legal_name,
        "registration_number": supplier.registration_number,
        "tax_identifier": supplier.tax_identifier,
        "country": supplier.country,
        "address": supplier.address,
        "contact_name": supplier.contact_name,
        "contact_email": supplier.contact_email,
        "contact_phone": supplier.contact_phone,
        "authorised_categories": supplier.authorised_categories,
        "authorised_brands": supplier.authorised_brands,
        "authorised_territories": supplier.authorised_territories,
        "licence_number": supplier.licence_number,
        "licence_issuer": supplier.licence_issuer,
        "licence_source_url": supplier.licence_source_url,
        "licence_valid_until": (
            supplier.licence_valid_until.isoformat()
            if supplier.licence_valid_until else None
        ),
        "next_review_date": (
            supplier.next_review_date.isoformat()
            if supplier.next_review_date else None
        ),
        "status": _effective_status(supplier),
        "submitted_by_user_id": str(supplier.submitted_by_user_id),
        "reviewed_by_user_id": (
            str(supplier.reviewed_by_user_id) if supplier.reviewed_by_user_id else None
        ),
        "reviewed_at": supplier.reviewed_at.isoformat() if supplier.reviewed_at else None,
        "review_notes": supplier.review_notes,
        "created_at": supplier.created_at.isoformat(),
        "updated_at": supplier.updated_at.isoformat(),
    }


@suppliers_bp.get("/suppliers")
@login_required
@company_permission_required("manage_suppliers")
def list_suppliers(_user):
    rows = db.session.scalars(
        select(Supplier)
        .where(Supplier.company_id == _company_id())
        .order_by(Supplier.legal_name)
        .limit(500)
    ).all()
    return jsonify({"items": [_supplier_json(row) for row in rows]})


@suppliers_bp.post("/suppliers")
@login_required
@company_permission_required("manage_suppliers")
def create_supplier(user):
    data = _json_object()
    if data is None:
        return jsonify({"error": "Send a JSON object."}), 400
    try:
        item = Supplier(
            company_id=_company_id(),
            legal_name=_text(data, "legal_name", 180, required=True),
            registration_number=_text(data, "registration_number", 120),
            tax_identifier=_text(data, "tax_identifier", 120),
            country=_country(data.get("country")),
            address=_text(data, "address", 500),
            contact_name=_text(data, "contact_name", 160),
            contact_email=_text(data, "contact_email", 320, lower=True),
            contact_phone=_text(data, "contact_phone", 40),
            authorised_categories=_string_list(
                data.get("authorised_categories"), "authorised_categories", lower=True
            ),
            authorised_brands=_string_list(
                data.get("authorised_brands"), "authorised_brands"
            ),
            authorised_territories=_string_list(
                data.get("authorised_territories"), "authorised_territories", upper=True
            ),
            licence_number=_text(data, "licence_number", 160),
            licence_issuer=_text(data, "licence_issuer", 180),
            licence_source_url=_text(data, "licence_source_url", 500),
            licence_valid_until=_optional_date(data.get("licence_valid_until"), "Licence expiry"),
            next_review_date=_optional_date(data.get("next_review_date"), "Next review date"),
            submitted_by_user_id=user.id,
            status="pending_review",
        )
        db.session.add(item)
        db.session.flush()
        record_audit_event(
            db.session, user.id, "supplier_created", item.company_id,
            {"supplier_id": str(item.id), "country": item.country},
        )
        result = _supplier_json(item)
        db.session.commit()
    except ValueError as error:
        db.session.rollback()
        return jsonify({"error": str(error)}), 400
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "The supplier could not be saved."}), 409
    return jsonify({"item": result}), 201


@suppliers_bp.patch("/suppliers/<uuid:supplier_id>")
@login_required
@company_permission_required("manage_suppliers")
def update_supplier(_user, supplier_id):
    company_id = _company_id()
    item = db.session.scalar(
        select(Supplier).where(
            Supplier.id == supplier_id, Supplier.company_id == company_id
        ).with_for_update()
    )
    if item is None:
        return jsonify({"error": "Supplier not found."}), 404
    data = _json_object()
    if data is None:
        return jsonify({"error": "Send a JSON object."}), 400
    identity_fields = {
        "legal_name", "registration_number", "tax_identifier", "country", "address",
        "contact_name", "contact_email", "contact_phone", "authorised_categories",
        "authorised_brands", "authorised_territories", "licence_number",
        "licence_issuer", "licence_source_url", "licence_valid_until", "next_review_date",
    }
    try:
        changed = bool(identity_fields.intersection(data))
        for key, maximum in (
            ("legal_name", 180), ("registration_number", 120), ("tax_identifier", 120),
            ("address", 500), ("contact_name", 160), ("contact_email", 320),
            ("contact_phone", 40), ("licence_number", 160), ("licence_issuer", 180),
            ("licence_source_url", 500),
        ):
            if key in data:
                setattr(item, key, _text(
                    data, key, maximum, required=(key == "legal_name"),
                    lower=(key == "contact_email"),
                ))
        if "country" in data:
            item.country = _country(data["country"])
        for key, upper, lower in (
            ("authorised_categories", False, True),
            ("authorised_brands", False, False),
            ("authorised_territories", True, False),
        ):
            if key in data:
                setattr(item, key, _string_list(
                    data[key], key, upper=upper, lower=lower
                ))
        if "licence_valid_until" in data:
            item.licence_valid_until = _optional_date(
                data["licence_valid_until"], "Licence expiry"
            )
        if "next_review_date" in data:
            item.next_review_date = _optional_date(
                data["next_review_date"], "Next review date"
            )
        if changed:
            item.status = "pending_review"
            item.reviewed_by_user_id = None
            item.reviewed_at = None
            item.review_notes = None
            record_audit_event(
                db.session, _user.id, "supplier_re_review_required", company_id,
                {"supplier_id": str(item.id), "changed_fields": sorted(identity_fields.intersection(data))},
            )
        db.session.flush()
        result = _supplier_json(item)
        db.session.commit()
    except ValueError as error:
        db.session.rollback()
        return jsonify({"error": str(error)}), 400
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "The supplier update could not be saved."}), 409
    return jsonify({"item": result})


@suppliers_bp.post("/suppliers/<uuid:supplier_id>/review")
@login_required
@company_permission_required("manage_suppliers")
def review_supplier(user, supplier_id):
    company_id = _company_id()
    item = db.session.scalar(
        select(Supplier).where(
            Supplier.id == supplier_id, Supplier.company_id == company_id
        ).with_for_update()
    )
    if item is None:
        return jsonify({"error": "Supplier not found."}), 404
    if item.submitted_by_user_id == user.id:
        return jsonify({"error": "A supplier submitter cannot approve or review their own submission."}), 403
    data = _json_object()
    if data is None:
        return jsonify({"error": "Send a JSON object."}), 400
    try:
        decision = _text(data, "decision", 24, required=True, lower=True)
        if decision not in {"approve", "restrict", "suspend", "reject"}:
            raise ValueError("Unsupported supplier review decision.")
        notes = _text(data, "notes", 1000)
        if decision in {"restrict", "suspend", "reject"} and not notes:
            raise ValueError("A reason is required for this supplier decision.")
        if decision == "approve":
            if not item.licence_number or not item.licence_issuer:
                raise ValueError("A licence number and issuing authority are required before approval.")
            if not item.licence_valid_until or item.licence_valid_until < date.today():
                raise ValueError("A current, unexpired supplier licence is required.")
            if not item.authorised_categories or not item.authorised_territories:
                raise ValueError("At least one authorised category and territory are required.")
            if item.country not in item.authorised_territories:
                raise ValueError("The supplier's registered country must be included in its authorised territories.")
            item.status = "approved"
            event_type = "supplier_approved"
        elif decision == "restrict":
            item.status = "restricted"
            event_type = "supplier_restricted"
        elif decision == "suspend":
            item.status = "suspended"
            event_type = "supplier_suspended"
        else:
            item.status = "rejected"
            event_type = "supplier_rejected"
        item.reviewed_by_user_id = user.id
        item.reviewed_at = datetime.now(timezone.utc)
        item.review_notes = notes
        record_audit_event(
            db.session, user.id, event_type, company_id,
            {"supplier_id": str(item.id), "decision": decision, "notes": notes},
        )
        db.session.flush()
        result = _supplier_json(item)
        db.session.commit()
    except ValueError as error:
        db.session.rollback()
        return jsonify({"error": str(error)}), 400
    return jsonify({"item": result})
