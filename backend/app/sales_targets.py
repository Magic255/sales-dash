"""Company-scoped monthly revenue targets and progress."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from flask import Blueprint, g, jsonify, request, session
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from .auth import login_required
from .extensions import db
from .models import CompanyMembership, Sale, SalesTarget, User
from .permissions import company_permission_required

targets_bp = Blueprint("sales_targets", __name__, url_prefix="/api")


def _company_id():
    return UUID(session["company_id"])


def _month(value):
    if not isinstance(value, str) or len(value) != 7:
        raise ValueError("Month must use YYYY-MM format.")
    try:
        parsed = date.fromisoformat(value + "-01")
    except ValueError:
        raise ValueError("Month must use YYYY-MM format.") from None
    if parsed.strftime("%Y-%m") != value:
        raise ValueError("Month must use YYYY-MM format.")
    return parsed


def _target_amount(value):
    if isinstance(value, bool) or value is None:
        raise ValueError("Target amount must be a positive number.")
    try:
        amount = Decimal(str(value))
        rounded = amount.quantize(Decimal("0.01"))
    except Exception:
        raise ValueError("Target amount must be a positive number.") from None
    if not amount.is_finite() or rounded <= 0 or amount != rounded:
        raise ValueError("Target amount must be a positive amount with up to 2 decimals.")
    if rounded > Decimal("999999999999.99"):
        raise ValueError("Target amount is too large.")
    return rounded


def _month_end(start):
    if start.month == 12:
        return date(start.year + 1, 1, 1)
    return date(start.year, start.month + 1, 1)


@targets_bp.get("/sales-targets")
@login_required
@company_permission_required("view_dashboard")
def list_sales_targets(user):
    company_id = _company_id()
    try:
        period_start = _month(request.args.get("month") or date.today().strftime("%Y-%m"))
    except ValueError:
        return jsonify({"error": "Choose a valid month in YYYY-MM format."}), 400
    period_end = _month_end(period_start)
    role = request.user_role if hasattr(request, "user_role") else None
    # The permission decorator has already refreshed the active membership.
    from flask import g
    role = g.company_membership.role

    targets = db.session.scalars(
        select(SalesTarget).where(
            SalesTarget.company_id == company_id,
            SalesTarget.period_start == period_start,
        ).order_by(SalesTarget.target_type, SalesTarget.currency)
    ).all()
    actual_rows = db.session.execute(
        select(
            Sale.salesperson_user_id, Sale.currency, func.sum(Sale.total_amount)
        ).where(
            Sale.company_id == company_id,
            Sale.status == "completed",
            Sale.sale_date >= period_start,
            Sale.sale_date < period_end,
        ).group_by(Sale.salesperson_user_id, Sale.currency)
    ).all()
    actual_by_owner_currency = {
        (owner_id, currency): amount for owner_id, currency, amount in actual_rows
    }
    company_actual = {}
    for (owner_id, currency), amount in actual_by_owner_currency.items():
        company_actual[currency] = company_actual.get(currency, Decimal("0.00")) + amount

    company_targets = []
    for target in targets:
        if target.target_type != "company":
            continue
        actual = company_actual.get(target.currency, Decimal("0.00"))
        company_targets.append({
            "currency": target.currency,
            "target_amount": str(target.target_amount),
            "actual_amount": str(actual),
            "progress_percent": str((actual / target.target_amount * 100).quantize(Decimal("0.01"))),
        })

    salesperson_targets = []
    visible_targets = [
        target for target in targets
        if target.target_type == "salesperson"
        and (role in {"admin", "manager"} or target.salesperson_user_id == user.id)
    ]
    for target in visible_targets:
        member = db.session.execute(
            select(User.display_name, User.email).join(
                CompanyMembership, CompanyMembership.user_id == User.id
            ).where(
                CompanyMembership.company_id == company_id,
                CompanyMembership.user_id == target.salesperson_user_id,
                CompanyMembership.status == "active",
            )
        ).first()
        if member is None:
            continue
        actual = actual_by_owner_currency.get(
            (target.salesperson_user_id, target.currency), Decimal("0.00")
        )
        salesperson_targets.append({
            "user_id": str(target.salesperson_user_id),
            "name": member.display_name or member.email,
            "currency": target.currency,
            "target_amount": str(target.target_amount),
            "actual_amount": str(actual),
            "progress_percent": str((actual / target.target_amount * 100).quantize(Decimal("0.01"))),
        })

    salespeople = []
    if role in {"admin", "manager"}:
        members = db.session.execute(
            select(User.id, User.display_name, User.email).join(
                CompanyMembership, CompanyMembership.user_id == User.id
            ).where(
                CompanyMembership.company_id == company_id,
                CompanyMembership.status == "active",
                CompanyMembership.role == "salesperson",
            ).order_by(User.email)
        ).all()
        salespeople = [
            {"user_id": str(member.id), "name": member.display_name or member.email}
            for member in members
        ]

    return jsonify({
        "month": period_start.strftime("%Y-%m"),
        "company_targets": company_targets,
        "salesperson_targets": salesperson_targets,
        "salespeople": salespeople,
    })


@targets_bp.put("/sales-targets")
@login_required
@company_permission_required("manage_sales_targets")
def save_sales_target(user):
    from flask import g

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Send a JSON object."}), 400
    try:
        period_start = _month(data.get("month"))
        target_type = data.get("target_type")
        if target_type not in {"company", "salesperson"}:
            raise ValueError("Choose a company or salesperson target.")
        currency = data.get("currency")
        if not isinstance(currency, str) or len(currency.strip()) != 3:
            raise ValueError("Currency must be a 3-letter code.")
        currency = currency.strip().upper()
        if not currency.isalpha():
            raise ValueError("Currency must be a 3-letter code.")
        target_amount = _target_amount(data.get("target_amount"))
        salesperson_id = None
        if target_type == "salesperson":
            salesperson_id = UUID(str(data.get("salesperson_user_id", "")))
            membership = db.session.scalar(select(CompanyMembership).where(
                CompanyMembership.company_id == _company_id(),
                CompanyMembership.user_id == salesperson_id,
                CompanyMembership.role == "salesperson",
                CompanyMembership.status == "active",
            ))
            if membership is None:
                raise ValueError("Choose an active salesperson in this company.")
        elif data.get("salesperson_user_id") not in (None, ""):
            raise ValueError("Company targets do not have a salesperson.")
    except (ValueError, TypeError):
        return jsonify({"error": "Check the month, target type, salesperson, currency and amount."}), 400

    company_id = _company_id()
    target = db.session.scalar(select(SalesTarget).where(
        SalesTarget.company_id == company_id,
        SalesTarget.period_start == period_start,
        SalesTarget.target_type == target_type,
        SalesTarget.salesperson_user_id == salesperson_id,
        SalesTarget.currency == currency,
    ))
    if target is None:
        target = SalesTarget(
            company_id=company_id,
            period_start=period_start,
            target_type=target_type,
            salesperson_user_id=salesperson_id,
            currency=currency,
            target_amount=target_amount,
        )
        db.session.add(target)
    else:
        target.target_amount = target_amount
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "The target could not be saved. Refresh and try again."}), 409

    return jsonify({
        "message": "Monthly target saved.",
        "item": {
            "month": period_start.strftime("%Y-%m"),
            "target_type": target_type,
            "salesperson_user_id": str(salesperson_id) if salesperson_id else None,
            "currency": currency,
            "target_amount": str(target_amount),
        },
    })
