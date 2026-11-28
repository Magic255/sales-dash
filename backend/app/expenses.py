"""Company-scoped expense recording and reporting APIs."""

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from uuid import UUID, uuid4

from flask import Blueprint, jsonify, request, session
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .audit import record_audit_event
from .auth import login_required
from .extensions import db
from .models import Expense
from .permissions import company_permission_required

expenses_bp = Blueprint("expenses", __name__, url_prefix="/api")


def _company_id():
    return UUID(session["company_id"])


def _expense_json(item):
    return {
        "id": str(item.id),
        "category": item.category,
        "description": item.description,
        "amount": str(item.amount),
        "currency": item.currency,
        "expense_date": item.expense_date.isoformat(),
        "payment_method": item.payment_method,
        "reference": item.reference,
        "notes": item.notes,
        "status": item.status,
        "void_reason": item.void_reason,
        "created_by_user_id": str(item.created_by_user_id),
        "created_at": item.created_at.isoformat(),
        "voided_at": item.voided_at.isoformat() if item.voided_at else None,
    }


def _payload():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValueError("Send a JSON object.")
    description = data.get("description")
    category = data.get("category")
    currency = data.get("currency", "TZS")
    if not isinstance(description, str) or not description.strip() or len(description.strip()) > 500:
        raise ValueError("Description is required and must be 500 characters or fewer.")
    if not isinstance(category, str):
        raise ValueError("Choose an expense category.")
    category = category.strip().lower().replace(" ", "_")
    if not category or len(category) > 60 or not category.replace("_", "").replace("-", "").isalnum():
        raise ValueError("Expense category must use letters, numbers, hyphens or underscores.")
    if not isinstance(currency, str) or len(currency.strip()) != 3 or not currency.strip().isascii() or not currency.strip().isalpha():
        raise ValueError("Currency must be a three-letter ISO code.")
    try:
        amount = Decimal(str(data.get("amount", "")))
        expense_date = date.fromisoformat(data.get("expense_date", ""))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError("Enter a valid amount and expense date.") from None
    if not amount.is_finite() or amount <= 0 or amount.as_tuple().exponent < -2:
        raise ValueError("Expense amount must be positive and use no more than two decimal places.")
    payment_method = data.get("payment_method")
    reference = data.get("reference")
    notes = data.get("notes")
    for field, value, maximum in (
        ("payment method", payment_method, 40),
        ("reference", reference, 120),
        ("notes", notes, 1000),
    ):
        if value is not None and (not isinstance(value, str) or len(value.strip()) > maximum):
            raise ValueError(f"{field.title()} must be {maximum} characters or fewer.")
    return {
        "description": description.strip(),
        "category": category,
        "amount": amount.quantize(Decimal("0.01")),
        "currency": currency.strip().upper(),
        "expense_date": expense_date,
        "payment_method": payment_method.strip() if payment_method else None,
        "reference": reference.strip() if reference else None,
        "notes": notes.strip() if notes else None,
    }


@expenses_bp.get("/expenses")
@login_required
@company_permission_required("manage_expenses")
def list_expenses(user):
    company_id = _company_id()
    query = select(Expense).where(Expense.company_id == company_id)
    status = request.args.get("status")
    category = request.args.get("category")
    currency = request.args.get("currency")
    start = request.args.get("from")
    end = request.args.get("to")
    try:
        if status:
            if status not in {"recorded", "void"}:
                raise ValueError
            query = query.where(Expense.status == status)
        if category:
            query = query.where(Expense.category == category.strip().lower())
        if currency:
            if len(currency) != 3:
                raise ValueError
            query = query.where(Expense.currency == currency.strip().upper())
        if start:
            query = query.where(Expense.expense_date >= date.fromisoformat(start))
        if end:
            query = query.where(Expense.expense_date <= date.fromisoformat(end))
        if start and end and date.fromisoformat(start) > date.fromisoformat(end):
            raise ValueError
    except ValueError:
        return jsonify({"error": "Invalid expense filters. Check dates, currency and status."}), 400
    items = db.session.scalars(
        query.order_by(Expense.expense_date.desc(), Expense.created_at.desc()).limit(500)
    ).all()
    totals = {}
    for item in items:
        if item.status == "recorded":
            totals[item.currency] = totals.get(item.currency, Decimal("0")) + item.amount
    return jsonify({
        "items": [_expense_json(item) for item in items],
        "totals_by_currency": [
            {"currency": currency_code, "amount": str(value)}
            for currency_code, value in sorted(totals.items())
        ],
    })


@expenses_bp.post("/expenses")
@login_required
@company_permission_required("manage_expenses")
def create_expense(user):
    try:
        values = _payload()
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    company_id = _company_id()
    item = Expense(
        id=uuid4(),
        company_id=company_id,
        created_by_user_id=user.id,
        **values,
    )
    db.session.add(item)
    try:
        db.session.flush()
        record_audit_event(
            db.session, user.id, "expense_created", company_id,
            {"expense_id": str(item.id), "category": item.category,
             "amount": str(item.amount), "currency": item.currency},
        )
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "The expense could not be saved. Refresh and try again."}), 409
    return jsonify({"item": _expense_json(item)}), 201


@expenses_bp.post("/expenses/<uuid:expense_id>/void")
@login_required
@company_permission_required("manage_expenses")
def void_expense(user, expense_id):
    data = request.get_json(silent=True)
    reason = data.get("reason") if isinstance(data, dict) else None
    if not isinstance(reason, str) or not reason.strip() or len(reason.strip()) > 500:
        return jsonify({"error": "A reason of 500 characters or fewer is required to void an expense."}), 400
    item = db.session.scalar(select(Expense).where(
        Expense.id == expense_id, Expense.company_id == _company_id()
    ).with_for_update())
    if item is None:
        return jsonify({"error": "Expense not found."}), 404
    if item.status != "recorded":
        return jsonify({"error": "Only recorded expenses can be voided."}), 409
    item.status = "void"
    item.void_reason = reason.strip()
    item.voided_by_user_id = user.id
    item.voided_at = datetime.now(timezone.utc)
    record_audit_event(
        db.session, user.id, "expense_voided", item.company_id,
        {"expense_id": str(item.id), "reason": item.void_reason},
    )
    db.session.commit()
    return jsonify({"item": _expense_json(item)})
