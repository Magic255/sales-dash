"""Company-scoped customer, product, sales, and dashboard APIs."""

import csv
import hashlib
import io
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal, InvalidOperation
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from cryptography.fernet import Fernet, InvalidToken
from flask import Blueprint, Response, current_app, g, jsonify, request, send_file, session
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from werkzeug.utils import secure_filename

from .audit import record_audit_event
from .auth import login_required
from .extensions import db
from .models import (
    AppNotification,
    CategoryCompliancePolicy,
    Company,
    CompanyMembership,
    ComplianceEvidenceFile,
    Customer,
    DiscountApprovalRequest,
    Product,
    Sale,
    SaleItem,
    StockBatch,
    StockMovement,
    User,
)
from .permissions import company_permission_required

sales_bp = Blueprint("sales", __name__, url_prefix="/api")
CENT = Decimal("0.01")
MILLI = Decimal("0.001")


def _company_id():
    return UUID(session["company_id"])


def _country_code(value, *, required=False):
    if value in (None, ""):
        if required:
            raise ValueError("A market country code is required.")
        return None
    if not isinstance(value, str):
        raise ValueError("Country must be a two-letter ISO country code.")
    result = value.strip().upper()
    if len(result) != 2 or not result.isascii() or not result.isalpha():
        raise ValueError("Country must be a two-letter ISO country code.")
    return result


def _category_compliance_policy(company_id, category_key, market_country):
    if not market_country:
        category_has_market_rules = db.session.scalar(
            select(func.count()).select_from(CategoryCompliancePolicy).where(
                CategoryCompliancePolicy.company_id == company_id,
                CategoryCompliancePolicy.category_key == category_key,
            )
        )
        if category_has_market_rules:
            raise ValueError(
                "Select the product's market country to apply its category compliance policy."
            )
        return None
    return db.session.scalar(
        select(CategoryCompliancePolicy).where(
            CategoryCompliancePolicy.company_id == company_id,
            CategoryCompliancePolicy.category_key == category_key,
            CategoryCompliancePolicy.market_country == market_country,
        )
    )


def _apply_category_compliance_policy(product):
    policy = _category_compliance_policy(
        product.company_id, product.category_key, product.market_country
    )
    if policy and policy.approval_mode in {"required", "admin_exception"}:
        product.compliance_required = True
    return policy


def _discount_limit(company, role):
    if role == "admin":
        return None
    if role == "manager":
        return company.manager_discount_limit
    if role == "salesperson":
        return company.salesperson_discount_limit
    return Decimal("0.00")


def _discount_percent(discount, subtotal):
    if subtotal <= 0:
        return Decimal("0.00")
    return (discount * Decimal("100") / subtotal).quantize(CENT, rounding=ROUND_HALF_UP)


def _record_discount_application(
    sale, user, prepared, order_discount, discount_percent,
    approval_request, previous_discount_amount,
):
    """Write an immutable audit event for every sale discount change."""
    if sale.discount_amount <= 0 and previous_discount_amount <= 0:
        return
    remaining = []
    for row in prepared:
        if len(row) == 5:
            product, quantity, unit_price, line_discount, line_total = row
        else:
            product, quantity, line_discount, line_total = row
            unit_price = product.unit_price
        remaining.append((
            product, quantity, unit_price, line_discount, line_total
        ))
    remaining_total = sum((row[4] for row in remaining), Decimal("0.00"))
    allocated = Decimal("0.00")
    item_details = []
    for index, (product, quantity, unit_price, line_discount, line_total) in enumerate(remaining):
        if index == len(remaining) - 1:
            order_share = order_discount - allocated
        elif remaining_total > 0:
            order_share = (
                order_discount * line_total / remaining_total
            ).quantize(CENT, rounding=ROUND_DOWN)
            allocated += order_share
        else:
            order_share = Decimal("0.00")
        effective_unit = (
            (line_total - order_share) / quantity
        ).quantize(CENT, rounding=ROUND_DOWN)
        item_details.append({
            "product_id": str(product.id),
            "sku": product.sku,
            "base_unit_price": str(unit_price),
            "effective_unit_price": str(effective_unit),
            "line_discount": str(line_discount),
            "allocated_order_discount": str(order_share),
        })
    record_audit_event(
        db.session,
        user.id,
        "discount_applied",
        sale.company_id,
        {
            "sale_id": str(sale.id),
            "sale_number": sale.sale_number,
            "currency": sale.currency,
            "old_discount_amount": str(previous_discount_amount),
            "new_discount_amount": str(sale.discount_amount),
            "discount_percent": str(discount_percent),
            "approval_request_id": (
                str(approval_request.id) if approval_request else None
            ),
            "approval_status": approval_request.status if approval_request else None,
            "approver_user_id": (
                str(approval_request.approver_user_id)
                if approval_request and approval_request.approver_user_id else None
            ),
            "items": item_details,
        },
    )


def _latest_discount_approval(sale_id, company_id):
    return db.session.scalar(
        select(DiscountApprovalRequest)
        .where(
            DiscountApprovalRequest.sale_id == sale_id,
            DiscountApprovalRequest.company_id == company_id,
        )
        .order_by(
            DiscountApprovalRequest.created_at.desc(),
            DiscountApprovalRequest.id.desc(),
        )
        .limit(1)
    )


def _queue_notification(
    company_id, recipient_user_id, notification_type, title, message, sale_id=None
):
    db.session.add(AppNotification(
        company_id=company_id,
        recipient_user_id=recipient_user_id,
        related_sale_id=sale_id,
        notification_type=notification_type,
        title=title,
        message=message,
    ))


def _queue_inventory_expiry_notifications(company_id, product, balances):
    """Create one private expiry alert per recipient and batch lifecycle event."""
    if not product.is_active:
        return False
    recipients = db.session.scalars(
        select(CompanyMembership).where(
            CompanyMembership.company_id == company_id,
            CompanyMembership.role.in_({"admin", "manager"}),
            CompanyMembership.status == "active",
        )
    ).all()
    if not recipients:
        return False

    created = False
    for row in balances:
        batch = row["batch"]
        quantity = max(row["on_hand"], Decimal("0.000"))
        if batch.expiry_date is None or quantity <= 0:
            continue
        if row["expired"]:
            notification_type = "inventory_batch_expired"
            title = "Inventory batch expired"
            message = (
                f"{product.name} ({product.sku}), batch {batch.batch_code}, "
                f"expired on {batch.expiry_date.isoformat()}; "
                f"{quantity} units remain and are excluded from sales."
            )
        elif row["expiring_soon"]:
            notification_type = "inventory_batch_expiring"
            title = "Inventory batch expiring soon"
            message = (
                f"{product.name} ({product.sku}), batch {batch.batch_code}, "
                f"has {quantity} units remaining and expires on "
                f"{batch.expiry_date.isoformat()}."
            )
        else:
            continue

        dedupe_key = f"batch:{batch.id}:{notification_type}"
        for recipient in recipients:
            try:
                with db.session.begin_nested():
                    db.session.add(AppNotification(
                        company_id=company_id,
                        recipient_user_id=recipient.user_id,
                        related_batch_id=batch.id,
                        dedupe_key=dedupe_key,
                        notification_type=notification_type,
                        title=title,
                        message=message[:500],
                    ))
                    db.session.flush()
                created = True
            except IntegrityError:
                # The unique recipient/dedupe key also handles concurrent refreshes.
                continue
    return created


def _create_discount_approval_if_needed(sale, user, discount_percent, reason):
    company = db.session.get(Company, sale.company_id)
    # Discount authority follows the credited salesperson, not the member
    # editing the draft. Completion uses this same membership role.
    salesperson_membership = db.session.get(
        CompanyMembership, (sale.company_id, sale.salesperson_user_id)
    )
    salesperson_role = (
        salesperson_membership.role if salesperson_membership else "viewer"
    )
    limit = _discount_limit(company, salesperson_role)
    previous = db.session.scalars(
        select(DiscountApprovalRequest)
        .where(
            DiscountApprovalRequest.sale_id == sale.id,
            DiscountApprovalRequest.company_id == sale.company_id,
            DiscountApprovalRequest.status.in_(("pending", "approved")),
        )
        .with_for_update()
    ).all()
    for approval in previous:
        approval.status = "superseded"

    if limit is None or discount_percent <= limit:
        return None
    if not reason:
        raise ValueError(
            "This discount is above your role limit. Add an approval reason."
        )
    approval = DiscountApprovalRequest(
        company_id=sale.company_id,
        sale_id=sale.id,
        requested_by_user_id=user.id,
        requested_discount_percent=discount_percent,
        reason=reason,
        status="pending",
    )
    db.session.add(approval)
    record_audit_event(
        db.session, user.id, "discount_approval_requested", sale.company_id,
        {
            "sale_id": str(sale.id),
            "discount_percent": str(discount_percent),
            "role_limit_percent": str(limit),
        },
    )
    admins = db.session.scalars(
        select(CompanyMembership).where(
            CompanyMembership.company_id == sale.company_id,
            CompanyMembership.role == "admin",
            CompanyMembership.status == "active",
        )
    ).all()
    for admin in admins:
        _queue_notification(
            sale.company_id,
            admin.user_id,
            "discount_approval_requested",
            "Discount approval needed",
            (
                f"Sale {sale.sale_number} needs approval for a "
                f"{discount_percent}% discount. Reason: {reason}"
            )[:500],
            sale.id,
        )
    return approval



class PriceFloorError(ValueError):
    """A sale violates the configured product minimum selling price."""


def _check_price_floor(prepared, order_discount, user, override_reason, sale_id):
    """Check each line after its line discount and proportional order discount."""
    remaining = []
    for row in prepared:
        if len(row) == 5:
            product, quantity, unit_price, discount, _line_total = row
            gross = (quantity * unit_price).quantize(CENT, rounding=ROUND_HALF_UP)
        else:
            product, quantity, discount, line_total = row
            gross = line_total + discount
        remaining.append((product, quantity, gross, discount, gross - discount))
    remaining_total = sum((row[4] for row in remaining), Decimal("0.00"))
    allocated = Decimal("0.00")
    violations = []
    for index, (product, quantity, gross, line_discount, remaining_line) in enumerate(remaining):
        if index == len(remaining) - 1:
            order_share = order_discount - allocated
        elif remaining_total > 0:
            order_share = (
                order_discount * remaining_line / remaining_total
            ).quantize(CENT, rounding=ROUND_DOWN)
            allocated += order_share
        else:
            order_share = Decimal("0.00")
        net_line = remaining_line - order_share
        effective_unit = (net_line / quantity).quantize(
            CENT, rounding=ROUND_DOWN
        )
        if effective_unit < product.minimum_selling_price:
            violations.append({
                "product_id": str(product.id),
                "sku": product.sku,
                "base_unit_price": str(product.unit_price),
                "minimum_selling_price": str(product.minimum_selling_price),
                "effective_unit_price": str(effective_unit),
                "line_discount": str(line_discount),
                "allocated_order_discount": str(order_share),
            })
    if not violations:
        return
    # The authoritative role is the active company membership, not a client field.
    if getattr(getattr(g, "company_membership", None), "role", None) != "admin":
        raise PriceFloorError("The discount would take a product below its minimum selling price.")
    reason = (override_reason or "").strip()
    if not reason:
        raise PriceFloorError("An Admin price-floor override requires a reason.")
    record_audit_event(
        db.session, user.id, "price_floor_override", _company_id(),
        {"sale_id": str(sale_id) if sale_id else None,
         "reason": reason, "items": violations},
    )


def _json_object():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else None


def _boolean(value, field):
    if not isinstance(value, bool):
        raise ValueError(f"{field.replace('_', ' ').capitalize()} must be true or false.")
    return value


def _text(data, field, maximum, *, required=False, lower=False, upper=False):
    value = data.get(field)
    if value is None:
        if required:
            raise ValueError(f"{field.replace('_', ' ').capitalize()} is required.")
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field.replace('_', ' ').capitalize()} must be text.")
    value = value.strip()
    if required and not value:
        raise ValueError(f"{field.replace('_', ' ').capitalize()} is required.")
    if len(value) > maximum:
        raise ValueError(f"{field.replace('_', ' ').capitalize()} is too long.")
    if lower:
        value = value.lower()
    if upper:
        value = value.upper()
    return value or None


def _decimal(value, field, *, minimum=Decimal("0"), places=CENT):
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{field.replace('_', ' ').capitalize()} is required.")
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f"{field.replace('_', ' ').capitalize()} must be a number.") from None
    if not amount.is_finite() or amount < minimum:
        raise ValueError(f"{field.replace('_', ' ').capitalize()} is invalid.")
    try:
        rounded = amount.quantize(places, rounding=ROUND_HALF_UP)
        if rounded < minimum:
            raise ValueError(f"{field.replace('_', ' ').capitalize()} is too small.")
        return rounded
    except InvalidOperation:
        raise ValueError(f"{field.replace('_', ' ').capitalize()} is invalid.") from None


def _customer_json(item):
    return {
        "id": str(item.id), "name": item.name, "email": item.email,
        "phone": item.phone, "organization": item.organization,
        "notes": item.notes, "is_active": item.is_active,
        "created_at": item.created_at.isoformat(),
    }


def _product_json(item, *, include_cost=False):
    result = {
        "id": str(item.id), "sku": item.sku, "name": item.name,
        "description": item.description, "unit_price": str(item.unit_price),
        "currency": item.currency, "is_active": item.is_active,
        "minimum_selling_price": str(item.minimum_selling_price),
        "track_inventory": item.track_inventory,
        "compliance_required": item.compliance_required,
        "category_key": item.category_key,
        "market_country": item.market_country,
        "low_stock_threshold": str(item.low_stock_threshold),
        "created_at": item.created_at.isoformat(),
    }
    if include_cost:
        result["cost_price"] = str(item.cost_price)
    return result


def _sale_json(item, customer_name=None, line_items=None):
    return {
        "id": str(item.id), "sale_number": item.sale_number,
        "customer_id": str(item.customer_id), "customer_name": customer_name,
        "salesperson_user_id": str(item.salesperson_user_id),
        "status": item.status, "sale_date": item.sale_date.isoformat(),
        "currency": item.currency, "subtotal": str(item.subtotal),
        "discount_amount": str(item.discount_amount),
        "tax_amount": str(item.tax_amount), "total_amount": str(item.total_amount),
        "notes": item.notes, "items": line_items or [],
        "created_at": item.created_at.isoformat(),
    }


@sales_bp.get("/customers")
@login_required
@company_permission_required("view_reports")
def list_customers(_user):
    company_id = _company_id()
    include_inactive = request.args.get("include_inactive") == "true"
    if include_inactive and g.company_membership.role not in {"admin", "manager"}:
        return jsonify({"error": "You are not allowed to view archived customers."}), 403
    query = select(Customer).where(Customer.company_id == company_id)
    if not include_inactive:
        query = query.where(Customer.is_active.is_(True))
    search = request.args.get("search", "").strip()
    if search:
        pattern = f"%{search[:100]}%"
        query = query.where(
            Customer.name.ilike(pattern)
            | Customer.email.ilike(pattern)
            | Customer.organization.ilike(pattern)
        )
    items = db.session.scalars(query.order_by(Customer.name).limit(100)).all()
    return jsonify({"items": [_customer_json(item) for item in items]})


@sales_bp.post("/customers")
@login_required
@company_permission_required("create_sales")
def create_customer(user):
    data = _json_object()
    if data is None:
        return jsonify({"error": "Send a JSON object."}), 400
    try:
        item = Customer(
            company_id=_company_id(),
            created_by_user_id=user.id,
            name=_text(data, "name", 160, required=True),
            email=_text(data, "email", 320, lower=True),
            phone=_text(data, "phone", 40),
            organization=_text(data, "organization", 160),
            notes=_text(data, "notes", 2000),
        )
        db.session.add(item)
        db.session.flush()
        result = _customer_json(item)
        db.session.commit()
    except ValueError:
        db.session.rollback()
        return jsonify({"error": "Invalid input. Check the submitted fields and try again."}), 400
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "A customer with that email already exists."}), 409
    return jsonify({"item": result}), 201


@sales_bp.patch("/customers/<uuid:customer_id>")
@login_required
@company_permission_required("manage_customers")
def update_customer(_user, customer_id):
    item = db.session.scalar(
        select(Customer).where(
            Customer.id == customer_id, Customer.company_id == _company_id()
        )
    )
    if item is None:
        return jsonify({"error": "Customer not found."}), 404
    data = _json_object()
    if data is None:
        return jsonify({"error": "Send a JSON object."}), 400
    try:
        for field, maximum in (
            ("name", 160), ("email", 320), ("phone", 40),
            ("organization", 160), ("notes", 2000),
        ):
            if field in data:
                setattr(item, field, _text(
                    data, field, maximum, required=(field == "name"),
                    lower=(field == "email"),
                ))
        if "is_active" in data:
            if not isinstance(data["is_active"], bool):
                raise ValueError("is_active must be true or false.")
            item.is_active = data["is_active"]
        db.session.flush()
        result = _customer_json(item)
        db.session.commit()
    except ValueError:
        db.session.rollback()
        return jsonify({"error": "Invalid input. Check the submitted fields and try again."}), 400
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "A customer with that email already exists."}), 409
    return jsonify({"item": result})


def _batch_balances(company_id, product_id):
    """Return FIFO-ordered batch balances calculated from the append-only ledger."""
    batches = db.session.scalars(
        select(StockBatch)
        .where(
            StockBatch.company_id == company_id,
            StockBatch.product_id == product_id,
        )
        .order_by(StockBatch.created_at, StockBatch.id)
    ).all()
    if not batches:
        return []
    totals = {
        batch.id: {
            "on_hand": Decimal("0.000"),
            "reserved": Decimal("0.000"),
            "sold": Decimal("0.000"),
            "inflows": Decimal("0.000"),
            "writeoffs": Decimal("0.000"),
        }
        for batch in batches
    }
    rows = db.session.execute(
        select(
            StockMovement.batch_id,
            StockMovement.movement_type,
            func.sum(StockMovement.quantity),
        )
        .where(
            StockMovement.company_id == company_id,
            StockMovement.product_id == product_id,
            StockMovement.batch_id.in_(list(totals)),
        )
        .group_by(StockMovement.batch_id, StockMovement.movement_type)
    ).all()
    for batch_id, movement_type, total in rows:
        quantity = Decimal(str(total or 0))
        if movement_type in {"received", "returned", "adjustment_increase"}:
            totals[batch_id]["on_hand"] += quantity
            totals[batch_id]["inflows"] += quantity
        elif movement_type == "sold":
            totals[batch_id]["on_hand"] -= quantity
            totals[batch_id]["sold"] += quantity
        elif movement_type in {"damaged", "adjustment_decrease"}:
            totals[batch_id]["on_hand"] -= quantity
            totals[batch_id]["writeoffs"] += quantity
        elif movement_type == "reserved":
            totals[batch_id]["reserved"] += quantity
        elif movement_type == "released":
            totals[batch_id]["reserved"] -= quantity
    today = date.today()
    return [
        {
            "batch": batch,
            "on_hand": totals[batch.id]["on_hand"],
            "reserved": totals[batch.id]["reserved"],
            "sold": totals[batch.id]["sold"],
            "inflows": totals[batch.id]["inflows"],
            "writeoffs": totals[batch.id]["writeoffs"],
            "available": totals[batch.id]["on_hand"] - totals[batch.id]["reserved"],
            "compliance_blocked": batch.compliance_status not in {
                "approved", "exception_approved", "verified_not_required"
            },
            "expired": batch.expiry_date is not None and batch.expiry_date < today,
            "expiring_soon": (
                batch.expiry_date is not None
                and today <= batch.expiry_date <= today + timedelta(days=30)
            ),
        }
        for batch in batches
    ]


def _stock_balance(company_id, product_id):
    """Return total on-hand/reserved and sellable stock (excluding expired batches)."""
    balances = _batch_balances(company_id, product_id)
    on_hand = sum((item["on_hand"] for item in balances), Decimal("0.000"))
    reserved = sum((item["reserved"] for item in balances), Decimal("0.000"))
    available = sum(
        (
            item["available"] for item in balances
            if not item["expired"] and not item["compliance_blocked"]
        ),
        Decimal("0.000"),
    )
    return on_hand, reserved, available


def _allocate_fifo_movements(
    company_id, product_id, quantity, movement_type, actor_user_id,
    reason, reference=None, allow_expired=False,
):
    """Allocate a negative/reservation movement across oldest eligible batches."""
    balances = _batch_balances(company_id, product_id)
    remaining = quantity
    created = []
    for item in balances:
        if (item["expired"] or item["compliance_blocked"]) and not allow_expired:
            continue
        capacity = item["reserved"] if movement_type == "released" else item["available"]
        if capacity <= 0:
            continue
        take = min(capacity, remaining)
        movement = StockMovement(
            company_id=company_id,
            product_id=product_id,
            batch_id=item["batch"].id,
            actor_user_id=actor_user_id,
            movement_type=movement_type,
            quantity=take,
            reason=reason,
            reference=reference,
        )
        db.session.add(movement)
        created.append(movement)
        remaining -= take
        if remaining <= 0:
            break
    if remaining > 0:
        raise ValueError("The movement exceeds eligible batch stock.")
    return created


def _stock_movement_json(item, batch=None):
    return {
        "id": str(item.id),
        "product_id": str(item.product_id),
        "batch_id": str(item.batch_id) if item.batch_id else None,
        "batch_code": batch.batch_code if batch else None,
        "expiry_date": batch.expiry_date.isoformat() if batch and batch.expiry_date else None,
        "movement_type": item.movement_type,
        "quantity": str(item.quantity),
        "reason": item.reason,
        "reference": item.reference,
        "actor_user_id": str(item.actor_user_id),
        "created_at": item.created_at.isoformat(),
    }


@sales_bp.get("/inventory")
@login_required
@company_permission_required("manage_inventory")
def inventory_summary(_user):
    company_id = _company_id()
    products = db.session.scalars(
        select(Product).where(
            Product.company_id == company_id,
            Product.track_inventory.is_(True),
        ).order_by(Product.name)
    ).all()
    items = []
    notifications_created = False
    for product in products:
        balances = _batch_balances(company_id, product.id)
        notifications_created = (
            _queue_inventory_expiry_notifications(company_id, product, balances)
            or notifications_created
        )
        on_hand = sum((row["on_hand"] for row in balances), Decimal("0.000"))
        reserved = sum((row["reserved"] for row in balances), Decimal("0.000"))
        expired_quantity = sum(
            (
                max(row["on_hand"], Decimal("0.000"))
                for row in balances if row["expired"]
            ),
            Decimal("0.000"),
        )
        available = sum(
            (
                row["available"] for row in balances
                if not row["expired"] and not row["compliance_blocked"]
            ),
            Decimal("0.000"),
        )
        expiring_soon_quantity = sum(
            (
                max(row["available"], Decimal("0.000"))
                for row in balances if row["expiring_soon"]
            ),
            Decimal("0.000"),
        )
        quarantine_quantity = sum(
            (
                max(row["on_hand"], Decimal("0.000"))
                for row in balances if row["compliance_blocked"]
            ),
            Decimal("0.000"),
        )
        sold_total = sum((row["sold"] for row in balances), Decimal("0.000"))
        inflows_total = sum((row["inflows"] for row in balances), Decimal("0.000"))
        writeoffs_total = sum((row["writeoffs"] for row in balances), Decimal("0.000"))
        status = (
            "discontinued" if not product.is_active
            else "expired" if available <= 0 and expired_quantity > 0
            else "pending_verification" if available <= 0 and quarantine_quantity > 0
            else "reserved" if available <= 0 and reserved > 0 and on_hand > 0
            else "sold" if (
                on_hand <= 0 and sold_total > 0
                and sold_total >= inflows_total and writeoffs_total == 0
            )
            else "out_of_stock" if available <= 0
            else "low_stock" if available <= product.low_stock_threshold
            else "available"
        )
        items.append({
            "product_id": str(product.id),
            "sku": product.sku,
            "name": product.name,
            "currency": product.currency,
            "stock_on_hand": str(on_hand),
            "reserved_quantity": str(reserved),
            "available_quantity": str(available),
            "expired_quantity": str(expired_quantity),
            "quarantine_quantity": str(quarantine_quantity),
            "expiring_soon_quantity": str(expiring_soon_quantity),
            "low_stock_threshold": str(product.low_stock_threshold),
            "status": status,
        })
    if notifications_created:
        db.session.commit()
    return jsonify({"items": items})


@sales_bp.get("/products/<uuid:product_id>/stock-batches")
@login_required
@company_permission_required("manage_inventory")
def list_stock_batches(_user, product_id):
    company_id = _company_id()
    product = db.session.scalar(
        select(Product).where(
            Product.id == product_id, Product.company_id == company_id
        )
    )
    if product is None:
        return jsonify({"error": "Product not found."}), 404
    if not product.track_inventory:
        return jsonify({"error": "Inventory tracking is not enabled for this product."}), 409
    items = []
    for row in _batch_balances(company_id, product_id):
        batch = row["batch"]
        items.append({
            "id": str(batch.id),
            "batch_code": batch.batch_code,
            "expiry_date": batch.expiry_date.isoformat() if batch.expiry_date else None,
            "compliance_status": batch.compliance_status,
            "supplier_name": batch.supplier_name,
            "supplier_invoice_reference": batch.supplier_invoice_reference,
            "delivery_note_reference": batch.delivery_note_reference,
            "manufacturer_name": batch.manufacturer_name,
            "country_of_origin": batch.country_of_origin,
            "qr_code_present": bool(batch.qr_code),
            "authority_name": batch.authority_name,
            "authority_role": batch.authority_role,
            "certificate_reference": batch.certificate_reference,
            "verification_method": batch.verification_method,
            "verification_source_url": batch.verification_source_url,
            "verification_reference": batch.verification_reference,
            "verified_product_identifier": batch.verified_product_identifier,
            "verified_scope": batch.verified_scope,
            "accreditation_body_name": batch.accreditation_body_name,
            "verified_at": batch.verified_at.isoformat() if batch.verified_at else None,
            "stock_on_hand": str(row["on_hand"]),
            "reserved_quantity": str(row["reserved"]),
            "available_quantity": str(
                Decimal("0.000")
                if row["expired"] or row["compliance_blocked"]
                else row["available"]
            ),
            "expired_quantity": str(
                max(row["on_hand"], Decimal("0.000")) if row["expired"]
                else Decimal("0.000")
            ),
            "status": (
                "expired" if row["expired"] and row["on_hand"] > 0
                else "pending_verification" if row["compliance_blocked"] and row["on_hand"] > 0
                else "reserved" if row["available"] <= 0 and row["reserved"] > 0
                else "sold" if (
                    row["on_hand"] <= 0 and row["sold"] > 0
                    and row["sold"] >= row["inflows"] and row["writeoffs"] == 0
                )
                else "out_of_stock" if row["available"] <= 0
                else "expiring_soon" if row["expiring_soon"]
                else "available"
            ),
            "received_at": batch.created_at.isoformat(),
        })
    return jsonify({"items": items})



def _compliance_evidence_cipher():
    key = current_app.config.get("COMPLIANCE_EVIDENCE_ENCRYPTION_KEY")
    if not isinstance(key, str) or not key:
        return None
    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, UnicodeEncodeError):
        return None


def _detect_compliance_evidence_type(content):
    if content.startswith(b"%PDF-"):
        return "application/pdf"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    return None


@sales_bp.post("/stock-batches/<uuid:batch_id>/evidence")
@login_required
@company_permission_required("manage_inventory")
def upload_stock_batch_compliance_evidence(user, batch_id):
    """Store encrypted, private evidence for one company-owned stock batch."""
    company_id = _company_id()
    if g.company_membership.role not in {"admin", "manager"}:
        return jsonify({"error": "Only authorised compliance verifiers can upload evidence."}), 403
    cipher = _compliance_evidence_cipher()
    if cipher is None:
        return jsonify({"error": "Private evidence storage is not configured."}), 503
    batch = db.session.scalar(
        select(StockBatch).where(
            StockBatch.id == batch_id,
            StockBatch.company_id == company_id,
        ).with_for_update()
    )
    if batch is None:
        return jsonify({"error": "Stock batch not found."}), 404
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        return jsonify({"error": "Choose a certificate or evidence file."}), 400
    filename = secure_filename(upload.filename)[:180]
    if not filename:
        return jsonify({"error": "The evidence filename is invalid."}), 400
    content = upload.stream.read(8 * 1024 * 1024 + 1)
    if not content or len(content) > 8 * 1024 * 1024:
        return jsonify({"error": "Evidence files must be between 1 byte and 8 MB."}), 400
    content_type = _detect_compliance_evidence_type(content)
    expected_extensions = {
        "application/pdf": {".pdf"},
        "image/jpeg": {".jpg", ".jpeg"},
        "image/png": {".png"},
        "image/webp": {".webp"},
    }
    extension = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if not content_type or extension not in expected_extensions.get(content_type, set()):
        return jsonify({
            "error": "Upload a genuine PDF, JPEG, PNG or WebP file with a matching extension."
        }), 400

    evidence = ComplianceEvidenceFile(
        company_id=company_id,
        batch_id=batch.id,
        uploaded_by_user_id=user.id,
        original_filename=filename,
        content_type=content_type,
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        encrypted_content=cipher.encrypt(content),
    )
    db.session.add(evidence)
    db.session.flush()
    record_audit_event(
        db.session, user.id, "product_compliance_evidence_uploaded", company_id,
        {
            "batch_id": str(batch.id),
            "evidence_file_id": str(evidence.id),
            "content_type": content_type,
            "size_bytes": len(content),
            "sha256": evidence.sha256,
        },
    )
    result = {
        "id": str(evidence.id),
        "filename": evidence.original_filename,
        "content_type": evidence.content_type,
        "size_bytes": evidence.size_bytes,
        "sha256": evidence.sha256,
        "created_at": evidence.created_at.isoformat() if evidence.created_at else None,
    }
    db.session.commit()
    return jsonify({"item": result}), 201


@sales_bp.get("/stock-batches/<uuid:batch_id>/evidence")
@login_required
@company_permission_required("manage_inventory")
def list_stock_batch_compliance_evidence(_user, batch_id):
    company_id = _company_id()
    if g.company_membership.role not in {"admin", "manager"}:
        return jsonify({"error": "Only authorised compliance verifiers can view evidence."}), 403
    batch = db.session.scalar(
        select(StockBatch).where(
            StockBatch.id == batch_id,
            StockBatch.company_id == company_id,
        )
    )
    if batch is None:
        return jsonify({"error": "Stock batch not found."}), 404
    rows = db.session.scalars(
        select(ComplianceEvidenceFile).where(
            ComplianceEvidenceFile.company_id == company_id,
            ComplianceEvidenceFile.batch_id == batch_id,
        ).order_by(ComplianceEvidenceFile.created_at.desc(), ComplianceEvidenceFile.id.desc())
    ).all()
    return jsonify({"items": [
        {
            "id": str(row.id),
            "filename": row.original_filename,
            "content_type": row.content_type,
            "size_bytes": row.size_bytes,
            "sha256": row.sha256,
            "created_at": row.created_at.isoformat(),
            "download_url": f"/api/stock-batches/{batch_id}/evidence/{row.id}",
        }
        for row in rows
    ]})


@sales_bp.get("/stock-batches/<uuid:batch_id>/evidence/<uuid:evidence_id>")
@login_required
@company_permission_required("manage_inventory")
def download_stock_batch_compliance_evidence(user, batch_id, evidence_id):
    company_id = _company_id()
    if g.company_membership.role not in {"admin", "manager"}:
        return jsonify({
            "error": "Only authorised compliance verifiers can download evidence."
        }), 403
    evidence = db.session.scalar(
        select(ComplianceEvidenceFile).where(
            ComplianceEvidenceFile.id == evidence_id,
            ComplianceEvidenceFile.batch_id == batch_id,
            ComplianceEvidenceFile.company_id == company_id,
        )
    )
    if evidence is None:
        return jsonify({"error": "Evidence file not found."}), 404
    cipher = _compliance_evidence_cipher()
    if cipher is None:
        return jsonify({"error": "Private evidence storage is not configured."}), 503
    try:
        content = cipher.decrypt(evidence.encrypted_content)
    except InvalidToken:
        current_app.logger.error(
            "Compliance evidence decryption failed for an authorised tenant record."
        )
        return jsonify({"error": "Evidence file is unavailable."}), 500
    if hashlib.sha256(content).hexdigest() != evidence.sha256:
        current_app.logger.error(
            "Compliance evidence integrity check failed for an authorised tenant record."
        )
        return jsonify({"error": "Evidence file is unavailable."}), 500
    record_audit_event(
        db.session, user.id, "product_compliance_evidence_downloaded", company_id,
        {"batch_id": str(batch_id), "evidence_file_id": str(evidence_id)},
    )
    db.session.commit()
    response = send_file(
        io.BytesIO(content),
        mimetype=evidence.content_type,
        as_attachment=True,
        download_name=evidence.original_filename,
        conditional=False,
        max_age=0,
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@sales_bp.post("/stock-batches/<uuid:batch_id>/compliance")
@login_required
@company_permission_required("manage_inventory")
def verify_stock_batch_compliance(user, batch_id):
    """Record an independent, evidence-backed compliance decision for one batch."""
    company_id = _company_id()
    batch = db.session.scalar(
        select(StockBatch).where(
            StockBatch.id == batch_id,
            StockBatch.company_id == company_id,
        ).with_for_update()
    )
    if batch is None:
        return jsonify({"error": "Stock batch not found."}), 404
    if g.company_membership.role not in {"admin", "manager"}:
        return jsonify({"error": "Only authorised compliance verifiers can review stock."}), 403
    if batch.received_by_user_id == user.id:
        return jsonify({"error": "The person who received this batch cannot verify it."}), 403
    data = _json_object()
    if data is None:
        return jsonify({"error": "Send a JSON object."}), 400
    try:
        decision = _text(data, "decision", 16, required=True, lower=True)
        if decision not in {
            "approve", "reject", "recall", "exception", "release_not_required"
        }:
            raise ValueError("Unsupported compliance decision.")
        notes = _text(data, "notes", 1000, required=(decision != "approve"))
        product = db.session.scalar(
            select(Product).where(
                Product.company_id == company_id, Product.id == batch.product_id
            )
        )
        policy = _category_compliance_policy(
            company_id, product.category_key, product.market_country
        ) if product else None
        if decision == "exception":
            if (
                g.company_membership.role != "admin"
                or not policy
                or policy.approval_mode != "admin_exception"
                or policy.legal_requirement
            ):
                return jsonify({
                    "error": "Admin exceptions are unavailable for legally required approvals."
                }), 403
            batch.compliance_status = "exception_approved"
            event_type = "product_compliance_exception"
        elif decision == "release_not_required":
            if (
                not policy
                or policy.approval_mode != "not_required"
                or policy.legal_requirement
            ):
                return jsonify({
                    "error": "A not-required category policy must be configured before release."
                }), 409
            evidence_file_id = UUID(_text(data, "evidence_file_id", 36, required=True))
            evidence_file = db.session.scalar(
                select(ComplianceEvidenceFile).where(
                    ComplianceEvidenceFile.id == evidence_file_id,
                    ComplianceEvidenceFile.company_id == company_id,
                    ComplianceEvidenceFile.batch_id == batch.id,
                )
            )
            if evidence_file is None:
                raise ValueError("Upload supplier/source evidence for this batch before release.")
            batch.evidence_reference = f"private-evidence:{evidence_file.id}"
            batch.compliance_status = "verified_not_required"
            event_type = "product_compliance_not_required_release"
        elif decision == "approve":
            qr_code = _text(data, "qr_code", 500, required=True)
            authority_name = _text(data, "authority_name", 160, required=True)
            authority_country = _country_code(data.get("authority_country"), required=True)
            authority_role = _text(data, "authority_role", 32, required=True, lower=True)
            if authority_role not in {
                "standards_body", "regulator", "certification_body",
                "accreditation_body", "testing_lab", "inspection_body", "other",
            }:
                raise ValueError("Unsupported issuing authority role.")
            certificate_reference = _text(
                data, "certificate_reference", 160, required=True
            )
            verification_method = _text(
                data, "verification_method", 32, required=True, lower=True
            )
            if verification_method not in {
                "official_registry", "accreditation_scope",
                "issuer_confirmation", "document_review",
            }:
                raise ValueError("Unsupported verification method.")
            verification_source_url = _text(data, "verification_source_url", 500)
            verification_reference = _text(data, "verification_reference", 200)
            verified_product_identifier = _text(
                data, "verified_product_identifier", 200, required=True
            )
            verified_scope = _text(data, "verified_scope", 300, required=True)
            accreditation_body_name = _text(data, "accreditation_body_name", 160)
            if verification_method in {"official_registry", "accreditation_scope"}:
                if not verification_source_url:
                    raise ValueError("An official HTTPS source URL is required.")
                parsed_source = urlsplit(verification_source_url)
                if (
                    parsed_source.scheme != "https"
                    or not parsed_source.hostname
                    or parsed_source.username
                    or parsed_source.password
                ):
                    raise ValueError("The verification source must be an HTTPS URL.")
            if verification_method == "issuer_confirmation" and not verification_reference:
                raise ValueError("Record the issuer confirmation reference.")
            if verification_method == "accreditation_scope" and not accreditation_body_name:
                raise ValueError("Record the accreditation body checked.")
            evidence_file_id = UUID(_text(data, "evidence_file_id", 36, required=True))
            evidence_file = db.session.scalar(
                select(ComplianceEvidenceFile).where(
                    ComplianceEvidenceFile.id == evidence_file_id,
                    ComplianceEvidenceFile.company_id == company_id,
                    ComplianceEvidenceFile.batch_id == batch.id,
                )
            )
            if evidence_file is None:
                raise ValueError("Upload private evidence for this batch before approval.")
            if policy and policy.legal_requirement and verification_method not in {
                "official_registry", "issuer_confirmation"
            }:
                raise ValueError(
                    "Legally required approval must be checked against an official registry "
                    "or confirmed directly with the issuing authority."
                )
            standard_reference = _text(data, "standard_reference", 160)
            if (
                policy
                and policy.approval_mode in {"required", "admin_exception"}
                and authority_name.casefold() not in {
                    value.casefold() for value in policy.accepted_authorities
                }
            ):
                raise ValueError("The issuing authority is not on this category policy allow-list.")
            batch.qr_code = qr_code
            batch.authority_name = authority_name
            batch.authority_country = authority_country
            batch.authority_role = authority_role
            batch.certificate_reference = certificate_reference
            batch.evidence_reference = f"private-evidence:{evidence_file.id}"
            batch.standard_reference = standard_reference
            batch.verification_method = verification_method
            batch.verification_source_url = verification_source_url
            batch.verification_reference = verification_reference
            batch.verified_product_identifier = verified_product_identifier
            batch.verified_scope = verified_scope
            batch.accreditation_body_name = accreditation_body_name
            batch.compliance_status = "approved"
            event_type = "product_compliance_verified"
        elif decision in {"reject", "recall"}:
            batch.compliance_status = "rejected" if decision == "reject" else "recalled"
            event_type = (
                "product_compliance_rejected" if decision == "reject"
                else "product_compliance_recalled"
            )
        batch.verified_by_user_id = user.id
        batch.verified_at = datetime.now(timezone.utc)
        batch.verification_notes = notes
        record_audit_event(
            db.session, user.id, event_type, company_id,
            {
                "product_id": str(batch.product_id),
                "batch_id": str(batch.id),
                "batch_code": batch.batch_code,
                "decision": decision,
                "authority_name": batch.authority_name,
                "authority_country": batch.authority_country,
                "authority_role": batch.authority_role,
                "certificate_reference": batch.certificate_reference,
                "verification_method": batch.verification_method,
                "verification_source_url": batch.verification_source_url,
                "verification_reference": batch.verification_reference,
                "verified_product_identifier": batch.verified_product_identifier,
                "verified_scope": batch.verified_scope,
                "accreditation_body_name": batch.accreditation_body_name,
                "qr_code_present": bool(batch.qr_code),
                "evidence_reference_present": bool(batch.evidence_reference),
                "evidence_file_id": str(evidence_file.id) if decision == "approve" else None,
                "notes": notes,
            },
        )
        db.session.flush()
        result = {
            "id": str(batch.id),
            "compliance_status": batch.compliance_status,
            "authority_name": batch.authority_name,
            "authority_country": batch.authority_country,
            "authority_role": batch.authority_role,
            "certificate_reference": batch.certificate_reference,
            "verification_method": batch.verification_method,
            "verification_source_url": batch.verification_source_url,
            "verification_reference": batch.verification_reference,
            "verified_product_identifier": batch.verified_product_identifier,
            "verified_scope": batch.verified_scope,
            "accreditation_body_name": batch.accreditation_body_name,
            "verified_at": batch.verified_at.isoformat(),
            "evidence_file_id": str(evidence_file.id) if decision == "approve" else None,
        }
        db.session.commit()
    except ValueError:
        db.session.rollback()
        return jsonify({
            "error": "Invalid compliance review. Check the required evidence and fields."
        }), 400
    return jsonify({"item": result})


@sales_bp.get("/products/<uuid:product_id>/stock-movements")
@login_required
@company_permission_required("manage_inventory")
def list_stock_movements(_user, product_id):
    company_id = _company_id()
    product = db.session.scalar(
        select(Product).where(
            Product.id == product_id, Product.company_id == company_id
        )
    )
    if product is None:
        return jsonify({"error": "Product not found."}), 404
    if not product.track_inventory:
        return jsonify({"error": "Inventory tracking is not enabled for this product."}), 409
    rows = db.session.scalars(
        select(StockMovement)
        .where(
            StockMovement.company_id == company_id,
            StockMovement.product_id == product_id,
        )
        .order_by(StockMovement.created_at.desc(), StockMovement.id.desc())
        .limit(200)
    ).all()
    on_hand, reserved, available = _stock_balance(company_id, product_id)
    batch_ids = {item.batch_id for item in rows if item.batch_id}
    batches = db.session.scalars(
        select(StockBatch).where(
            StockBatch.company_id == company_id,
            StockBatch.id.in_(batch_ids),
        )
    ).all() if batch_ids else []
    batch_by_id = {batch.id: batch for batch in batches}
    return jsonify({
        "items": [
            _stock_movement_json(item, batch_by_id.get(item.batch_id))
            for item in rows
        ],
        "balance": {
            "stock_on_hand": str(on_hand),
            "reserved_quantity": str(reserved),
            "available_quantity": str(available),
        },
    })


@sales_bp.post("/products/<uuid:product_id>/stock-movements")
@login_required
@company_permission_required("manage_inventory")
def create_stock_movement(user, product_id):
    company_id = _company_id()
    product = db.session.scalar(
        select(Product).where(
            Product.id == product_id, Product.company_id == company_id
        ).with_for_update()
    )
    if product is None:
        return jsonify({"error": "Product not found."}), 404
    if not product.track_inventory:
        return jsonify({"error": "Enable inventory tracking for this product first."}), 409
    data = _json_object()
    if data is None:
        return jsonify({"error": "Send a JSON object."}), 400
    try:
        movement_type = _text(data, "movement_type", 24, required=True, lower=True)
        allowed = {
            "received", "returned", "damaged", "adjustment_increase",
            "adjustment_decrease", "reserved", "released",
        }
        if movement_type not in allowed:
            raise ValueError("Unsupported stock movement type.")
        if movement_type.startswith("adjustment_") and g.company_membership.role != "admin":
            return jsonify({"error": "Only Admins can make stock adjustments."}), 403
        quantity = _decimal(
            data.get("quantity"), "quantity",
            minimum=Decimal("0.001"), places=MILLI,
        )
        reason = _text(data, "reason", 1000, required=True)
        reference = _text(data, "reference", 120)
        created = []
        if movement_type in {"received", "returned", "adjustment_increase"}:
            batch_code = _text(data, "batch_code", 80, required=True)
            supplier_name = _text(data, "supplier_name", 160, required=(movement_type == "received"))
            supplier_invoice_reference = _text(
                data, "supplier_invoice_reference", 120,
                required=(movement_type == "received"),
            )
            delivery_note_reference = _text(data, "delivery_note_reference", 120)
            manufacturer_name = _text(
                data, "manufacturer_name", 160, required=(movement_type == "received")
            )
            country_of_origin = _country_code(
                data.get("country_of_origin"), required=(movement_type == "received")
            )
            if movement_type == "received" and not (
                supplier_invoice_reference or delivery_note_reference
            ):
                raise ValueError("A supplier invoice or delivery note reference is required.")
            raw_expiry = data.get("expiry_date")
            if raw_expiry in (None, ""):
                expiry_date = None
            elif not isinstance(raw_expiry, str):
                raise ValueError("Expiry date must use YYYY-MM-DD.")
            else:
                try:
                    expiry_date = date.fromisoformat(raw_expiry)
                except ValueError:
                    raise ValueError("Expiry date must use YYYY-MM-DD.") from None
            batch = StockBatch(
                company_id=company_id,
                product_id=product_id,
                batch_code=batch_code,
                expiry_date=expiry_date,
                supplier_name=supplier_name,
                supplier_invoice_reference=supplier_invoice_reference,
                delivery_note_reference=delivery_note_reference,
                manufacturer_name=manufacturer_name,
                country_of_origin=country_of_origin,
                compliance_status="pending_verification",
                received_by_user_id=user.id,
                created_at=datetime.now(timezone.utc),
            )
            db.session.add(batch)
            db.session.flush()
            created.append(StockMovement(
                company_id=company_id,
                product_id=product_id,
                batch_id=batch.id,
                actor_user_id=user.id,
                movement_type=movement_type,
                quantity=quantity,
                reason=reason,
                reference=reference,
            ))
        else:
            created.extend(_allocate_fifo_movements(
                company_id,
                product_id,
                quantity,
                movement_type,
                user.id,
                reason,
                reference,
                allow_expired=movement_type in {
                    "damaged", "adjustment_decrease", "released"
                },
            ))
        db.session.add_all(created)
        db.session.flush()
        on_hand, reserved, available = _stock_balance(company_id, product_id)
        result = [_stock_movement_json(movement) for movement in created]
        db.session.commit()
    except ValueError as error:
        db.session.rollback()
        return jsonify({"error": str(error)}), 400
    except IntegrityError:
        db.session.rollback()
        return jsonify({
            "error": "The batch code already exists or the stock movement could not be recorded."
        }), 409
    return jsonify({
        "item": result[0] if result else None,
        "items": result,
        "balance": {
            "stock_on_hand": str(on_hand),
            "reserved_quantity": str(reserved),
            "available_quantity": str(available),
        },
    }), 201




@sales_bp.get("/compliance-policies")
@login_required
@company_permission_required("manage_product_catalog")
def list_category_compliance_policies(_user):
    rows = db.session.scalars(
        select(CategoryCompliancePolicy)
        .where(CategoryCompliancePolicy.company_id == _company_id())
        .order_by(
            CategoryCompliancePolicy.market_country,
            CategoryCompliancePolicy.category_key,
        )
    ).all()
    return jsonify({"items": [
        {
            "id": str(row.id),
            "category_key": row.category_key,
            "market_country": row.market_country,
            "approval_mode": row.approval_mode,
            "legal_requirement": row.legal_requirement,
            "requirement_source_url": row.requirement_source_url,
            "requirement_reference": row.requirement_reference,
            "accepted_authorities": row.accepted_authorities,
            "updated_at": row.updated_at.isoformat(),
        }
        for row in rows
    ]})


@sales_bp.post("/compliance-policies")
@login_required
@company_permission_required("manage_product_catalog")
def save_category_compliance_policy(user):
    data = _json_object()
    if data is None:
        return jsonify({"error": "Send a JSON object."}), 400
    try:
        category_key = _text(data, "category_key", 80, required=True, lower=True)
        if not all(char.isascii() and (char.isalnum() or char in "-_") for char in category_key):
            raise ValueError("Invalid category key.")
        market_country = _country_code(data.get("market_country"), required=True)
        approval_mode = _text(data, "approval_mode", 24, required=True, lower=True)
        if approval_mode not in {"required", "admin_exception", "not_required"}:
            raise ValueError("Unsupported category approval mode.")
        legal_requirement = _boolean(data.get("legal_requirement", False), "legal_requirement")
        requirement_source_url = _text(data, "requirement_source_url", 500)
        requirement_reference = _text(data, "requirement_reference", 200)
        if legal_requirement and approval_mode != "required":
            raise ValueError("Legally required approvals must use the strict required mode.")
        if requirement_source_url:
            parsed_requirement_source = urlsplit(requirement_source_url)
            if (
                parsed_requirement_source.scheme != "https"
                or not parsed_requirement_source.hostname
                or parsed_requirement_source.username
                or parsed_requirement_source.password
            ):
                raise ValueError("The legal requirement source must be an HTTPS URL.")
        if legal_requirement and not (requirement_source_url and requirement_reference):
            raise ValueError("Record the official legal source URL and requirement reference.")
        authorities = data.get("accepted_authorities", [])
        if not isinstance(authorities, list) or len(authorities) > 30:
            raise ValueError("Accepted authorities must be a list of up to 30 names.")
        if approval_mode == "required" and not authorities:
            raise ValueError("Add at least one accepted authority for a required-approval policy.")
        cleaned = []
        for authority in authorities:
            if (
                not isinstance(authority, str)
                or not authority.strip()
                or len(authority.strip()) > 160
            ):
                raise ValueError("Each authority must have a valid name.")
            name = authority.strip()
            if name.casefold() not in {entry.casefold() for entry in cleaned}:
                cleaned.append(name)
        company_id = _company_id()
        policy = db.session.scalar(
            select(CategoryCompliancePolicy).where(
                CategoryCompliancePolicy.company_id == company_id,
                CategoryCompliancePolicy.category_key == category_key,
                CategoryCompliancePolicy.market_country == market_country,
            ).with_for_update()
        )
        if policy is None:
            policy = CategoryCompliancePolicy(
                company_id=company_id, category_key=category_key,
                market_country=market_country, approval_mode=approval_mode,
                accepted_authorities=cleaned, updated_by_user_id=user.id,
                legal_requirement=legal_requirement,
                requirement_source_url=requirement_source_url,
                requirement_reference=requirement_reference,
            )
            db.session.add(policy)
        else:
            policy.approval_mode = approval_mode
            policy.accepted_authorities = cleaned
            policy.legal_requirement = legal_requirement
            policy.requirement_source_url = requirement_source_url
            policy.requirement_reference = requirement_reference
            policy.updated_by_user_id = user.id
        affected = db.session.scalars(
            select(Product).where(
                Product.company_id == company_id,
                Product.category_key == category_key,
                Product.market_country == market_country,
            ).with_for_update()
        ).all()
        if approval_mode in {"required", "admin_exception"}:
            for product in affected:
                product.compliance_required = True
        for product in affected:
            batches = db.session.scalars(
                select(StockBatch).where(
                    StockBatch.company_id == company_id,
                    StockBatch.product_id == product.id,
                    StockBatch.compliance_status.in_(
                        ["approved", "exception_approved", "verified_not_required"]
                    ),
                ).with_for_update()
            ).all()
            for batch in batches:
                batch.compliance_status = "pending_verification"
        record_audit_event(
            db.session, user.id, "product_compliance_policy_updated", company_id,
            {
                "category_key": category_key, "market_country": market_country,
                "approval_mode": approval_mode, "accepted_authorities": cleaned,
                "legal_requirement": legal_requirement,
                "requirement_source_url": requirement_source_url,
                "requirement_reference": requirement_reference,
                "affected_products": len(affected),
            },
        )
        result = {
            "category_key": policy.category_key,
            "market_country": policy.market_country,
            "approval_mode": policy.approval_mode,
            "legal_requirement": policy.legal_requirement,
            "requirement_source_url": policy.requirement_source_url,
            "requirement_reference": policy.requirement_reference,
            "accepted_authorities": policy.accepted_authorities,
            "affected_products": len(affected),
        }
        db.session.commit()
        return jsonify({"item": result})
    except ValueError:
        db.session.rollback()
        return jsonify({"error": "Invalid category compliance policy."}), 400
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "A category policy already exists for this market."}), 409


@sales_bp.get("/products")
@login_required
@company_permission_required("view_reports")
def list_products(_user):
    company_id = _company_id()
    include_inactive = request.args.get("include_inactive") == "true"
    if include_inactive and g.company_membership.role not in {"admin", "manager"}:
        return jsonify({"error": "You are not allowed to view archived products."}), 403
    query = select(Product).where(Product.company_id == company_id)
    if not include_inactive:
        query = query.where(Product.is_active.is_(True))
    search = request.args.get("search", "").strip()
    if search:
        pattern = f"%{search[:100]}%"
        query = query.where(Product.name.ilike(pattern) | Product.sku.ilike(pattern))
    items = db.session.scalars(query.order_by(Product.name).limit(100)).all()
    return jsonify({"items": [
        _product_json(item, include_cost=(g.company_membership.role == "admin"))
        for item in items
    ]})


@sales_bp.post("/products")
@login_required
@company_permission_required("manage_product_catalog")
def create_product(user):
    data = _json_object()
    if data is None:
        return jsonify({"error": "Send a JSON object."}), 400
    try:
        item = Product(
            company_id=_company_id(),
            created_by_user_id=user.id,
            sku=_text(data, "sku", 64, required=True, upper=True),
            name=_text(data, "name", 160, required=True),
            description=_text(data, "description", 2000),
            unit_price=_decimal(data.get("unit_price"), "unit_price"),
            currency=_text(data, "currency", 3, required=True, upper=True),
            cost_price=_decimal(data.get("cost_price", "0"), "cost_price"),
            minimum_selling_price=_decimal(
                data.get("minimum_selling_price", data.get("cost_price", "0")),
                "minimum_selling_price",
            ),
            track_inventory=_boolean(data.get("track_inventory", False), "track_inventory"),
            compliance_required=_boolean(
                data.get("compliance_required", False), "compliance_required"
            ),
            category_key=_text(data, "category_key", 80, lower=True) or "general",
            market_country=_country_code(data.get("market_country")),
            low_stock_threshold=_decimal(
                data.get("low_stock_threshold", "0"), "low_stock_threshold",
                places=MILLI,
            ),
        )
        if not all(
            char.isascii() and (char.isalnum() or char in "-_")
            for char in item.category_key
        ):
            raise ValueError("Category must use letters, numbers, hyphens or underscores.")
        _apply_category_compliance_policy(item)
        if len(item.currency) != 3:
            raise ValueError("Currency must be a 3-letter code, such as TZS.")
        if item.minimum_selling_price < item.cost_price:
            raise ValueError("Minimum selling price cannot be below product cost.")
        if item.unit_price < item.minimum_selling_price:
            raise ValueError("Unit price cannot be below the minimum selling price.")
        if item.low_stock_threshold < 0:
            raise ValueError("Low-stock threshold cannot be negative.")
        db.session.add(item)
        db.session.flush()
        record_audit_event(
            db.session, user.id, "product_created", _company_id(),
            {"product_id": str(item.id), "sku": item.sku, "name": item.name,
             "unit_price": str(item.unit_price), "cost_price": str(item.cost_price),
             "minimum_selling_price": str(item.minimum_selling_price),
             "track_inventory": item.track_inventory,
             "category_key": item.category_key,
             "market_country": item.market_country,
             "compliance_required": item.compliance_required,
             "low_stock_threshold": str(item.low_stock_threshold),
             "currency": item.currency},
        )
        result = _product_json(item, include_cost=True)
        db.session.commit()
    except ValueError:
        db.session.rollback()
        return jsonify({"error": "Invalid input. Check the submitted fields and try again."}), 400
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "That SKU already exists in this company."}), 409
    return jsonify({"item": result}), 201


@sales_bp.patch("/products/<uuid:product_id>")
@login_required
@company_permission_required("manage_product_catalog")
def update_product(user, product_id):
    item = db.session.scalar(
        select(Product).where(
            Product.id == product_id, Product.company_id == _company_id()
        ).with_for_update()
    )
    if item is None:
        return jsonify({"error": "Product not found."}), 404
    data = _json_object()
    if data is None:
        return jsonify({"error": "Send a JSON object."}), 400
    if data.get("track_inventory") is False and item.track_inventory:
        movement_count = db.session.scalar(
            select(func.count()).select_from(StockMovement).where(
                StockMovement.company_id == _company_id(),
                StockMovement.product_id == item.id,
            )
        )
        if movement_count:
            return jsonify({
                "error": "Inventory tracking cannot be disabled after stock movements are recorded."
            }), 409
    before = {
        "sku": item.sku, "name": item.name, "description": item.description,
        "unit_price": str(item.unit_price), "cost_price": str(item.cost_price),
        "minimum_selling_price": str(item.minimum_selling_price),
        "track_inventory": item.track_inventory,
        "compliance_required": item.compliance_required,
        "category_key": item.category_key,
        "market_country": item.market_country,
        "low_stock_threshold": str(item.low_stock_threshold),
        "currency": item.currency, "is_active": item.is_active,
    }
    try:
        if "sku" in data:
            item.sku = _text(data, "sku", 64, required=True, upper=True)
        if "name" in data:
            item.name = _text(data, "name", 160, required=True)
        if "description" in data:
            item.description = _text(data, "description", 2000)
        if "unit_price" in data:
            item.unit_price = _decimal(data["unit_price"], "unit_price")
        if "cost_price" in data:
            item.cost_price = _decimal(data["cost_price"], "cost_price")
        if "minimum_selling_price" in data:
            item.minimum_selling_price = _decimal(
                data["minimum_selling_price"], "minimum_selling_price"
            )
        if "track_inventory" in data:
            item.track_inventory = _boolean(data["track_inventory"], "track_inventory")
        if "category_key" in data:
            item.category_key = _text(data, "category_key", 80, required=True, lower=True)
            if not all(
                char.isascii() and (char.isalnum() or char in "-_")
                for char in item.category_key
            ):
                raise ValueError("Category must use letters, numbers, hyphens or underscores.")
        if "market_country" in data:
            item.market_country = _country_code(data["market_country"])
        if "compliance_required" in data:
            item.compliance_required = _boolean(
                data["compliance_required"], "compliance_required"
            )
        _apply_category_compliance_policy(item)
        if item.compliance_required:
            compliance_enabled = (
                not before["compliance_required"] and item.compliance_required
            )
            reclassified = (
                "category_key" in data or "market_country" in data or compliance_enabled
            )
            if reclassified:
                eligible_statuses = ["approved", "exception_approved", "verified_not_required"]
                require_unverified = False
            else:
                eligible_statuses = ["approved"]
                require_unverified = True
            batch_query = select(StockBatch).where(
                StockBatch.company_id == item.company_id,
                StockBatch.product_id == item.id,
                StockBatch.compliance_status.in_(eligible_statuses),
            )
            if require_unverified:
                batch_query = batch_query.where(
                    StockBatch.verified_by_user_id.is_(None)
                )
            existing_batches = db.session.scalars(
                batch_query.with_for_update()
            ).all()
            for batch in existing_batches:
                batch.compliance_status = "pending_verification"
        if "low_stock_threshold" in data:
            item.low_stock_threshold = _decimal(
                data["low_stock_threshold"], "low_stock_threshold", places=MILLI
            )
        if item.low_stock_threshold < 0:
            raise ValueError("Low-stock threshold cannot be negative.")
        if item.minimum_selling_price < item.cost_price:
            raise ValueError("Minimum selling price cannot be below product cost.")
        if item.unit_price < item.minimum_selling_price:
            raise ValueError("Unit price cannot be below the minimum selling price.")
        if "currency" in data:
            item.currency = _text(data, "currency", 3, required=True, upper=True)
            if len(item.currency) != 3:
                raise ValueError("Currency must be a 3-letter code, such as TZS.")
        if "is_active" in data:
            if not isinstance(data["is_active"], bool):
                raise ValueError("is_active must be true or false.")
            item.is_active = data["is_active"]
        db.session.flush()
        after = {
            "sku": item.sku, "name": item.name, "description": item.description,
            "unit_price": str(item.unit_price), "cost_price": str(item.cost_price),
            "minimum_selling_price": str(item.minimum_selling_price),
            "track_inventory": item.track_inventory,
            "compliance_required": item.compliance_required,
            "category_key": item.category_key,
            "market_country": item.market_country,
            "low_stock_threshold": str(item.low_stock_threshold),
            "currency": item.currency, "is_active": item.is_active,
        }
        if before != after:
            record_audit_event(
                db.session, user.id, "product_updated", _company_id(),
                {"product_id": str(item.id), "old": before, "new": after},
            )
        result = _product_json(item, include_cost=True)
        db.session.commit()
    except ValueError:
        db.session.rollback()
        return jsonify({"error": "Invalid input. Check the submitted fields and try again."}), 400
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "That SKU already exists in this company."}), 409
    return jsonify({"item": result})


@sales_bp.get("/sales")
@login_required
@company_permission_required("view_reports")
def list_sales(_user):
    company_id = _company_id()
    query = (
        select(Sale, Customer.name)
        .join(
            Customer,
            (Customer.id == Sale.customer_id)
            & (Customer.company_id == Sale.company_id),
        )
        .where(Sale.company_id == company_id)
    )
    status = request.args.get("status")
    if status in {"draft", "completed", "void"}:
        query = query.where(Sale.status == status)
    rows = db.session.execute(
        query.order_by(Sale.sale_date.desc(), Sale.created_at.desc()).limit(100)
    ).all()
    return jsonify({"items": [_sale_json(item, name) for item, name in rows]})


@sales_bp.post("/sales")
@login_required
@company_permission_required("create_sales")
def create_sale(user):
    data = _json_object()
    if data is None:
        return jsonify({"error": "Send a JSON object."}), 400
    company_id = _company_id()
    try:
        try:
            customer_id = UUID(str(data.get("customer_id", "")))
        except (ValueError, TypeError):
            raise ValueError("Invalid customer identifier.") from None
        customer = db.session.scalar(select(Customer).where(
            Customer.id == customer_id, Customer.company_id == company_id,
            Customer.is_active.is_(True),
        ))
        if customer is None:
            raise ValueError("Choose an active customer in this company.")

        raw_items = data.get("items")
        if not isinstance(raw_items, list) or not 1 <= len(raw_items) <= 50:
            raise ValueError("A sale must contain between 1 and 50 items.")

        currency = _text(data, "currency", 3, required=True, upper=True)
        if len(currency) != 3:
            raise ValueError("Currency must be a 3-letter code, such as TZS.")
        sale_date_value = data.get("sale_date") or date.today().isoformat()
        try:
            sale_date = date.fromisoformat(sale_date_value)
        except (TypeError, ValueError):
            raise ValueError("Sale date must use YYYY-MM-DD format.") from None

        prepared = []
        subtotal = Decimal("0.00")
        line_discounts = Decimal("0.00")
        for raw in raw_items:
            if not isinstance(raw, dict):
                raise ValueError("Each sale item must be an object.")
            try:
                product_id = UUID(str(raw.get("product_id", "")))
            except (ValueError, TypeError):
                raise ValueError("Choose a valid product.") from None
            product = db.session.scalar(select(Product).where(
                Product.id == product_id, Product.company_id == company_id,
                Product.is_active.is_(True),
            ))
            if product is None:
                raise ValueError("A selected product is unavailable in this company.")
            if product.currency != currency:
                raise ValueError("All products in a sale must use the sale currency.")
            quantity = _decimal(
                raw.get("quantity"), "quantity",
                minimum=Decimal("0.001"), places=MILLI,
            )
            unit_price = product.unit_price
            gross = (quantity * unit_price).quantize(CENT, rounding=ROUND_HALF_UP)
            discount = _decimal(raw.get("discount_amount", "0"), "item discount")
            if discount > gross:
                raise ValueError("An item discount cannot exceed its line amount.")
            line_total = gross - discount
            subtotal += gross
            line_discounts += discount
            prepared.append((product, quantity, unit_price, discount, line_total))

        order_discount = _decimal(data.get("discount_amount", "0"), "discount_amount")
        tax = _decimal(data.get("tax_amount", "0"), "tax_amount")
        if order_discount > subtotal - line_discounts:
            raise ValueError("The sale discount is greater than the remaining amount.")
        total = subtotal - line_discounts - order_discount + tax
        discount_percent = _discount_percent(line_discounts + order_discount, subtotal)
        approval_reason = _text(data, "approval_reason", 1000)
        price_floor_override_reason = _text(
            data, "price_floor_override_reason", 1000
        )
        if total < 0:
            raise ValueError("The sale total cannot be negative.")

        sale = Sale(
            id=uuid4(), company_id=company_id,
            sale_number=f"SD-{date.today():%Y%m%d}-{uuid4().hex[:8].upper()}",
            customer_id=customer.id, salesperson_user_id=user.id,
            created_by_user_id=user.id, status="draft", sale_date=sale_date,
            currency=currency, subtotal=subtotal,
            discount_amount=line_discounts + order_discount,
            tax_amount=tax, total_amount=total,
            notes=_text(data, "notes", 2000),
        )
        db.session.add(sale)
        db.session.flush()
        _check_price_floor(
            prepared, order_discount, user, price_floor_override_reason, sale.id
        )
        approval_request = _create_discount_approval_if_needed(
            sale, user, discount_percent, approval_reason
        )
        _record_discount_application(
            sale, user, prepared, order_discount, discount_percent,
            approval_request, Decimal("0.00"),
        )
        for product, quantity, unit_price, discount, line_total in prepared:
            db.session.add(SaleItem(
                company_id=company_id, sale_id=sale.id, product_id=product.id,
                product_name=product.name, sku_snapshot=product.sku,
                quantity=quantity, unit_price=unit_price,
                discount_amount=discount, line_total=line_total,
            ))
        db.session.flush()
        result = _sale_json(
            sale, customer.name,
            [{"product_name": p.name, "sku": p.sku, "quantity": str(q),
              "unit_price": str(price), "discount_amount": str(discount),
              "line_total": str(line_total)}
             for p, q, price, discount, line_total in prepared],
        )
        result["approval_status"] = (
            approval_request.status if approval_request else None
        )
        db.session.commit()
    except PriceFloorError as error:
        db.session.rollback()
        return jsonify({"error": str(error)}), 400
    except ValueError:
        db.session.rollback()
        return jsonify({"error": "Invalid input. Check the submitted fields and try again."}), 400
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "The sale could not be saved. Refresh and try again."}), 409

    return jsonify({"item": result}), 201




def _sale_line_items(sale_id, company_id):
    rows = db.session.execute(
        select(SaleItem, Product.name, Product.sku)
        .join(
            Product,
            (Product.id == SaleItem.product_id)
            & (Product.company_id == SaleItem.company_id),
        )
        .where(
            SaleItem.sale_id == sale_id,
            SaleItem.company_id == company_id,
        )
        .order_by(SaleItem.created_at, SaleItem.id)
    ).all()
    return [
        {
            "id": str(line.id),
            "product_id": str(line.product_id),
            "product_name": line.product_name,
            "sku": line.sku_snapshot,
            "quantity": str(line.quantity),
            "unit_price": str(line.unit_price),
            "discount_amount": str(line.discount_amount),
            "line_total": str(line.line_total),
        }
        for line, _name, _sku in rows
    ]


def _parse_report_date(value, field):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field} must use YYYY-MM-DD format.") from None


def _report_sales_query(company_id):
    query = (
        select(Sale, Customer.name)
        .join(
            Customer,
            (Customer.id == Sale.customer_id)
            & (Customer.company_id == Sale.company_id),
        )
        .where(Sale.company_id == company_id)
    )
    try:
        start_date = _parse_report_date(request.args.get("from"), "Start date")
        end_date = _parse_report_date(request.args.get("to"), "End date")
        if start_date and end_date and start_date > end_date:
            raise ValueError("Start date must be on or before end date.")
        if start_date:
            query = query.where(Sale.sale_date >= start_date)
        if end_date:
            query = query.where(Sale.sale_date <= end_date)
        status = request.args.get("status")
        if status:
            if status not in {"draft", "completed", "void"}:
                raise ValueError("Choose a valid sale status.")
            query = query.where(Sale.status == status)
        salesperson = request.args.get("salesperson_user_id")
        if salesperson:
            try:
                salesperson_id = UUID(salesperson)
            except (ValueError, TypeError):
                raise ValueError("Salesperson identifier is invalid.") from None
            query = query.where(Sale.salesperson_user_id == salesperson_id)
    except ValueError:
        raise
    return query


@sales_bp.get("/reports/sales")
@login_required
@company_permission_required("view_reports")
def sales_report(_user):
    company_id = _company_id()
    try:
        query = _report_sales_query(company_id)
    except ValueError:
        return jsonify({"error": "Invalid report filters. Check the dates and selections."}), 400
    rows = db.session.execute(
        query.order_by(Sale.sale_date.desc(), Sale.created_at.desc()).limit(500)
    ).all()
    items = []
    totals = {}
    for sale, customer_name in rows:
        items.append(_sale_json(
            sale, customer_name,
            _sale_line_items(sale.id, company_id),
        ))
        if sale.status == "completed":
            totals[sale.currency] = totals.get(sale.currency, Decimal("0.00")) + sale.total_amount
    return jsonify({
        "items": items,
        "count": len(items),
        "limited": len(items) == 500,
        "completed_totals_by_currency": [
            {"currency": currency, "amount": str(amount)}
            for currency, amount in sorted(totals.items())
        ],
    })


def _csv_safe(value):
    text = "" if value is None else str(value)
    if text.lstrip(" \t\r\n").startswith(("=", "+", "-", "@")):
        return "'" + text
    return text


@sales_bp.get("/reports/discounts/weekly")
@login_required
@company_permission_required("view_reports")
def weekly_discount_report(_user):
    """Summarize completed-sale discount use by credited seller for one calendar week."""
    if g.company_membership.role not in {"admin", "manager"}:
        return jsonify({"error": "You are not allowed to view team discount performance."}), 403
    today = date.today()
    default_week_start = today - timedelta(days=today.weekday())
    try:
        week_start = date.fromisoformat(
            request.args.get("week_start", default_week_start.isoformat())
        )
        if week_start.weekday() != 0:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({
            "error": "Choose a valid Monday as the start of the reporting week."
        }), 400
    week_end = week_start + timedelta(days=6)
    company_id = _company_id()
    rows = db.session.execute(
        select(
            Sale.salesperson_user_id,
            User.display_name,
            User.email,
            Sale.currency,
            func.count(Sale.id),
            func.coalesce(func.sum(Sale.subtotal), 0),
            func.coalesce(func.sum(Sale.discount_amount), 0),
            func.coalesce(func.sum(Sale.subtotal - Sale.discount_amount), 0),
        )
        .join(User, User.id == Sale.salesperson_user_id)
        .where(
            Sale.company_id == company_id,
            Sale.status == "completed",
            Sale.sale_date >= week_start,
            Sale.sale_date <= week_end,
        )
        .group_by(
            Sale.salesperson_user_id, User.display_name, User.email, Sale.currency
        )
        .order_by(User.email, Sale.currency)
    ).all()
    salespeople = {}
    for seller_id, display_name, email, currency, count, subtotal, discount, revenue in rows:
        seller = salespeople.setdefault(str(seller_id), {
            "user_id": str(seller_id),
            "name": display_name or email,
            "email": email,
            "by_currency": [],
        })
        discount_rate = (
            (Decimal(str(discount)) * Decimal("100") / Decimal(str(subtotal)))
            .quantize(CENT, rounding=ROUND_HALF_UP)
            if Decimal(str(subtotal)) > 0 else Decimal("0.00")
        )
        seller["by_currency"].append({
            "currency": currency,
            "completed_sales": count,
            "subtotal": str(subtotal),
            "discount_total": str(discount),
            "discount_rate_percent": str(discount_rate),
            "net_sales_after_discount": str(revenue),
        })
    return jsonify({
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "salespeople": list(salespeople.values()),
        "note": (
            "Conversion rate is not included because this workspace does not yet "
            "track leads or opportunities."
        ),
    })


@sales_bp.get("/reports/sales.csv")
@login_required
@company_permission_required("view_reports")
def export_sales_report(_user):
    company_id = _company_id()
    try:
        query = _report_sales_query(company_id)
    except ValueError:
        return jsonify({"error": "Invalid report filters. Check the dates and selections."}), 400
    rows = db.session.execute(
        query.order_by(Sale.sale_date.desc(), Sale.created_at.desc()).limit(5000)
    ).all()
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow([
        "Sale number", "Sale date", "Customer", "Status", "Currency",
        "Subtotal", "Discount", "Tax", "Total", "Notes",
    ])
    for sale, customer_name in rows:
        writer.writerow([
            _csv_safe(sale.sale_number), sale.sale_date.isoformat(),
            _csv_safe(customer_name), sale.status, sale.currency,
            str(sale.subtotal), str(sale.discount_amount), str(sale.tax_amount),
            str(sale.total_amount), _csv_safe(sale.notes),
        ])
    return Response(
        output.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="sales-report.csv"',
            "Cache-Control": "no-store",
        },
    )


@sales_bp.patch("/sales/<uuid:sale_id>")
@login_required
@company_permission_required("edit_sales")
def update_draft_sale(user, sale_id):
    company_id = _company_id()
    sale = db.session.scalar(
        select(Sale)
        .where(Sale.id == sale_id, Sale.company_id == company_id)
        .with_for_update()
    )
    if sale is None:
        return jsonify({"error": "Sale not found."}), 404
    if sale.status != "draft":
        return jsonify({"error": "Only draft sales can be edited."}), 409
    data = _json_object()
    if data is None:
        return jsonify({"error": "Send a JSON object."}), 400
    try:
        customer_id = UUID(str(data.get("customer_id", "")))
        customer = db.session.scalar(select(Customer).where(
            Customer.id == customer_id,
            Customer.company_id == company_id,
            Customer.is_active.is_(True),
        ))
        if customer is None:
            raise ValueError("Choose an active customer.")
        currency = _text(data, "currency", 3, required=True, upper=True)
        if len(currency) != 3:
            raise ValueError("Currency must be a 3-letter code.")
        raw_items = data.get("items")
        if not isinstance(raw_items, list) or not 1 <= len(raw_items) <= 50:
            raise ValueError("A sale must contain between 1 and 50 items.")
        prepared = []
        subtotal = Decimal("0.00")
        line_discounts = Decimal("0.00")
        for raw in raw_items:
            if not isinstance(raw, dict):
                raise ValueError("Each sale item must be an object.")
            product_id = UUID(str(raw.get("product_id", "")))
            product = db.session.scalar(select(Product).where(
                Product.id == product_id,
                Product.company_id == company_id,
                Product.is_active.is_(True),
            ))
            if product is None or product.currency != currency:
                raise ValueError("Choose an available product in the sale currency.")
            quantity = _decimal(
                raw.get("quantity"), "quantity",
                minimum=Decimal("0.001"), places=MILLI,
            )
            gross = (quantity * product.unit_price).quantize(CENT, rounding=ROUND_HALF_UP)
            discount = _decimal(raw.get("discount_amount", "0"), "item discount")
            if discount > gross:
                raise ValueError("An item discount cannot exceed its line amount.")
            subtotal += gross
            line_discounts += discount
            prepared.append((product, quantity, discount, gross - discount))
        order_discount = _decimal(data.get("discount_amount", "0"), "discount_amount")
        tax = _decimal(data.get("tax_amount", "0"), "tax_amount")
        if order_discount > subtotal - line_discounts:
            raise ValueError("The sale discount is greater than the remaining amount.")
        total = subtotal - line_discounts - order_discount + tax
        discount_percent = _discount_percent(line_discounts + order_discount, subtotal)
        approval_reason = _text(data, "approval_reason", 1000)
        if total < 0:
            raise ValueError("The sale total cannot be negative.")
        sale_date = _parse_report_date(
            data.get("sale_date") or sale.sale_date.isoformat(), "Sale date"
        )
        previous_discount_amount = sale.discount_amount
        sale.customer_id = customer.id
        sale.currency = currency
        sale.sale_date = sale_date
        sale.subtotal = subtotal
        sale.discount_amount = line_discounts + order_discount
        sale.tax_amount = tax
        sale.total_amount = total
        sale.notes = _text(data, "notes", 2000)
        for old_item in db.session.scalars(select(SaleItem).where(
            SaleItem.sale_id == sale.id,
            SaleItem.company_id == company_id,
        )).all():
            db.session.delete(old_item)
        db.session.flush()
        approval_request = _create_discount_approval_if_needed(
            sale, user, discount_percent, approval_reason
        )
        _record_discount_application(
            sale, user, prepared, order_discount, discount_percent,
            approval_request, previous_discount_amount,
        )
        for product, quantity, discount, line_total in prepared:
            db.session.add(SaleItem(
                company_id=company_id,
                sale_id=sale.id,
                product_id=product.id,
                product_name=product.name,
                sku_snapshot=product.sku,
                quantity=quantity,
                unit_price=product.unit_price,
                discount_amount=discount,
                line_total=line_total,
            ))
        db.session.flush()
        result = _sale_json(sale, customer.name, [
            {"product_name": p.name, "sku": p.sku, "quantity": str(q),
             "unit_price": str(p.unit_price), "discount_amount": str(discount),
             "line_total": str(line_total)}
            for p, q, discount, line_total in prepared
        ])
        result["approval_status"] = (
            approval_request.status if approval_request else None
        )
        db.session.commit()
    except PriceFloorError as error:
        db.session.rollback()
        return jsonify({"error": str(error)}), 400
    except (ValueError, TypeError):
        db.session.rollback()
        return jsonify({"error": "Invalid input. Check the submitted fields and try again."}), 400
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "The sale could not be updated. Refresh and try again."}), 409
    return jsonify({"item": result})


@sales_bp.get("/discount-approvals")
@login_required
@company_permission_required("manage_discount_approvals")
def list_discount_approvals(_user):
    company_id = _company_id()
    rows = db.session.execute(
        select(DiscountApprovalRequest, Sale.sale_number, User.display_name, User.email)
        .join(
            Sale,
            (Sale.id == DiscountApprovalRequest.sale_id)
            & (Sale.company_id == DiscountApprovalRequest.company_id),
        )
        .join(User, User.id == DiscountApprovalRequest.requested_by_user_id)
        .where(
            DiscountApprovalRequest.company_id == company_id,
            DiscountApprovalRequest.status == "pending",
        )
        .order_by(DiscountApprovalRequest.created_at.asc())
        .limit(100)
    ).all()
    return jsonify({"items": [{
        "id": str(item.id),
        "sale_id": str(item.sale_id),
        "sale_number": sale_number,
        "requested_by": display_name or email,
        "requested_discount_percent": str(item.requested_discount_percent),
        "reason": item.reason,
        "created_at": item.created_at.isoformat(),
    } for item, sale_number, display_name, email in rows]})


@sales_bp.post("/discount-approvals/<uuid:approval_id>/decision")
@login_required
@company_permission_required("manage_discount_approvals")
def decide_discount_approval(user, approval_id):
    company_id = _company_id()
    data = _json_object()
    if data is None or set(data) - {"decision", "reason"}:
        return jsonify({"error": "Provide an approval decision."}), 400
    decision = data.get("decision")
    if decision not in {"approve", "reject"}:
        return jsonify({"error": "Choose approve or reject."}), 400
    try:
        decision_reason = _text(data, "reason", 1000, required=(decision == "reject"))
    except ValueError:
        return jsonify({"error": "A reason is required when rejecting a request."}), 400

    approval = db.session.scalar(
        select(DiscountApprovalRequest)
        .where(
            DiscountApprovalRequest.id == approval_id,
            DiscountApprovalRequest.company_id == company_id,
        )
        .with_for_update()
    )
    if approval is None:
        return jsonify({"error": "Approval request not found."}), 404
    if approval.status != "pending":
        return jsonify({"error": "This approval request has already been decided."}), 409
    if approval.requested_by_user_id == user.id:
        return jsonify({"error": "You cannot approve your own discount request."}), 403
    sale = db.session.scalar(
        select(Sale)
        .where(Sale.id == approval.sale_id, Sale.company_id == company_id)
        .with_for_update()
    )
    if sale is None or sale.status != "draft":
        return jsonify({"error": "Only requests for draft sales can be decided."}), 409

    approval.status = "approved" if decision == "approve" else "rejected"
    approval.approver_user_id = user.id
    approval.decision_reason = decision_reason
    approval.decided_at = func.now()
    record_audit_event(
        db.session, user.id, "discount_approval_decided", company_id,
        {
            "approval_id": str(approval.id),
            "sale_id": str(sale.id),
            "decision": approval.status,
            "requested_discount_percent": str(approval.requested_discount_percent),
            "requester_user_id": str(approval.requested_by_user_id),
        },
    )
    _queue_notification(
        company_id,
        approval.requested_by_user_id,
        "discount_approval_decided",
        "Discount request " + approval.status,
        (
            f"Your discount request for sale {sale.sale_number} was "
            f"{approval.status} by an Admin."
        ),
        sale.id,
    )
    db.session.commit()
    return jsonify({"item": {
        "id": str(approval.id),
        "status": approval.status,
        "approver_user_id": str(approval.approver_user_id),
        "decided_at": approval.decided_at.isoformat(),
    }})


def _notification_json(item):
    return {
        "id": str(item.id),
        "notification_type": item.notification_type,
        "title": item.title,
        "message": item.message,
        "related_sale_id": str(item.related_sale_id) if item.related_sale_id else None,
        "related_batch_id": str(item.related_batch_id) if item.related_batch_id else None,
        "read_at": item.read_at.isoformat() if item.read_at else None,
        "created_at": item.created_at.isoformat(),
    }


@sales_bp.get("/notifications")
@login_required
@company_permission_required("view_dashboard")
def list_notifications(user):
    company_id = _company_id()
    rows = db.session.scalars(
        select(AppNotification)
        .where(
            AppNotification.company_id == company_id,
            AppNotification.recipient_user_id == user.id,
        )
        .order_by(AppNotification.created_at.desc(), AppNotification.id.desc())
        .limit(50)
    ).all()
    unread_count = db.session.scalar(
        select(func.count()).select_from(AppNotification).where(
            AppNotification.company_id == company_id,
            AppNotification.recipient_user_id == user.id,
            AppNotification.read_at.is_(None),
        )
    ) or 0
    return jsonify({
        "items": [_notification_json(item) for item in rows],
        "unread_count": unread_count,
    })


@sales_bp.post("/notifications/<uuid:notification_id>/read")
@login_required
@company_permission_required("view_dashboard")
def mark_notification_read(user, notification_id):
    item = db.session.scalar(
        select(AppNotification)
        .where(
            AppNotification.id == notification_id,
            AppNotification.company_id == _company_id(),
            AppNotification.recipient_user_id == user.id,
        )
        .with_for_update()
    )
    if item is None:
        return jsonify({"error": "Notification not found."}), 404
    if item.read_at is None:
        item.read_at = datetime.now(timezone.utc)
        db.session.flush()
    result = _notification_json(item)
    db.session.commit()
    return jsonify({"item": result})


@sales_bp.post("/sales/<uuid:sale_id>/complete")
@login_required
@company_permission_required("create_sales")
def complete_sale(user, sale_id):
    item = db.session.scalar(
        select(Sale)
        .where(Sale.id == sale_id, Sale.company_id == _company_id())
        .with_for_update()
    )
    if item is None:
        return jsonify({"error": "Sale not found."}), 404
    if item.status != "draft":
        return jsonify({"error": "Only draft sales can be completed."}), 409
    if g.company_membership.role not in {"admin", "manager"} and item.created_by_user_id != user.id:
        return jsonify({"error": "You can only complete sales you created."}), 403
    company = db.session.get(Company, item.company_id)
    creator_membership = db.session.get(
        CompanyMembership, (item.company_id, item.salesperson_user_id)
    )
    limit = _discount_limit(company, creator_membership.role if creator_membership else "viewer")
    discount_percent = _discount_percent(item.discount_amount, item.subtotal)
    if limit is not None and discount_percent > limit:
        approval = _latest_discount_approval(item.id, item.company_id)
        if approval is None or approval.requested_discount_percent != discount_percent:
            return jsonify({
                "error": "A current discount approval is required before completion."
            }), 409
        if approval.status == "pending":
            return jsonify({"error": "This sale is waiting for Admin approval."}), 409
        if approval.status != "approved":
            return jsonify({
                "error": "The discount request was not approved. "
                "Update the sale or request approval again."
            }), 409
    sale_lines = db.session.scalars(
        select(SaleItem).where(
            SaleItem.sale_id == item.id,
            SaleItem.company_id == item.company_id,
        )
    ).all()
    product_ids = {line.product_id for line in sale_lines}
    current_products = db.session.scalars(
        select(Product).where(
            Product.company_id == item.company_id,
            Product.id.in_(product_ids),
        ).order_by(Product.id).with_for_update()
    ).all() if product_ids else []
    products_by_id = {product.id: product for product in current_products}
    if len(products_by_id) != len(product_ids):
        return jsonify({
            "error": "A product on this sale is no longer available for price validation."
        }), 409
    if any(not product.is_active for product in current_products):
        return jsonify({"error": "Discontinued products cannot be sold."}), 409
    line_discount_total = sum(
        (line.discount_amount for line in sale_lines), Decimal("0.00")
    )
    order_discount = item.discount_amount - line_discount_total
    try:
        request_data = request.get_json(silent=True) or {}
        override_reason = _text(
            request_data, "price_floor_override_reason", 1000
        ) if isinstance(request_data, dict) else ""
        _check_price_floor(
            [
                (products_by_id[line.product_id], line.quantity,
                 line.unit_price, line.discount_amount, line.line_total)
                for line in sale_lines
            ],
            max(order_discount, Decimal("0.00")),
            user,
            override_reason,
            item.id,
        )
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    tracked_quantities = {}
    for line in sale_lines:
        product = products_by_id[line.product_id]
        if product.track_inventory:
            tracked_quantities[line.product_id] = (
                tracked_quantities.get(line.product_id, Decimal("0.000"))
                + line.quantity
            )
    for tracked_product_id, required_quantity in tracked_quantities.items():
        _on_hand, _reserved, available = _stock_balance(
            item.company_id, tracked_product_id
        )
        if required_quantity > available:
            balances = _batch_balances(item.company_id, tracked_product_id)
            if any(row["compliance_blocked"] and row["available"] > 0 for row in balances):
                return jsonify({
                    "error": "Stock is quarantined pending product compliance verification."
                }), 409
            return jsonify({
                "error": "Insufficient available stock in non-expired batches for "
                + products_by_id[tracked_product_id].sku + "."
            }), 409
    try:
        for tracked_product_id, sold_quantity in tracked_quantities.items():
            _allocate_fifo_movements(
                item.company_id,
                tracked_product_id,
                sold_quantity,
                "sold",
                user.id,
                "Stock issued for completed sale " + item.sale_number,
                item.sale_number,
                allow_expired=False,
            )
    except ValueError:
        db.session.rollback()
        return jsonify({
            "error": "Insufficient available stock in non-expired batches."
        }), 409
    item.status = "completed"
    db.session.flush()
    result = _sale_json(item)
    db.session.commit()
    return jsonify({"item": result})


@sales_bp.post("/sales/<uuid:sale_id>/void")
@login_required
@company_permission_required("delete_sales")
def void_sale(user, sale_id):
    item = db.session.scalar(select(Sale).where(
        Sale.id == sale_id, Sale.company_id == _company_id()
    ).with_for_update())
    if item is None:
        return jsonify({"error": "Sale not found."}), 404
    if item.status == "void":
        return jsonify({"error": "This sale is already void."}), 409
    if item.status == "completed":
        lines = db.session.scalars(
            select(SaleItem).where(
                SaleItem.company_id == item.company_id,
                SaleItem.sale_id == item.id,
            )
        ).all()
        product_ids = {line.product_id for line in lines}
        tracked_products = db.session.scalars(
            select(Product).where(
                Product.company_id == item.company_id,
                Product.id.in_(product_ids),
            ).order_by(Product.id).with_for_update()
        ).all() if product_ids else []
        tracked_ids = {
            product.id for product in tracked_products if product.track_inventory
        }
        sold_movements = db.session.scalars(
            select(StockMovement).where(
                StockMovement.company_id == item.company_id,
                StockMovement.reference == item.sale_number,
                StockMovement.movement_type == "sold",
                StockMovement.product_id.in_(tracked_ids),
            ).order_by(StockMovement.created_at, StockMovement.id)
        ).all() if tracked_ids else []
        for sold in sold_movements:
            db.session.add(StockMovement(
                company_id=item.company_id,
                product_id=sold.product_id,
                batch_id=sold.batch_id,
                actor_user_id=user.id,
                movement_type="returned",
                quantity=sold.quantity,
                reason="Stock returned to original batch because sale "
                + item.sale_number + " was voided",
                reference=item.sale_number,
            ))
    item.status = "void"
    db.session.flush()
    result = _sale_json(item)
    db.session.commit()
    return jsonify({"item": result})


@sales_bp.get("/dashboard/analytics")
@login_required
@company_permission_required("view_dashboard")
def dashboard_analytics(_user):
    """Return completed-sales trends for a bounded dashboard date range."""
    today = date.today()
    try:
        default_from = (today - timedelta(days=29)).isoformat()
        date_from = date.fromisoformat(request.args.get("from", default_from))
        date_to = date.fromisoformat(request.args.get("to", today.isoformat()))
        if date_from > date_to or (date_to - date_from).days > 366:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify(
            {"error": "Invalid dashboard date range. Choose a range of up to 367 days."}
        ), 400

    rows = db.session.execute(
        select(Sale.sale_date, Sale.currency, func.sum(Sale.total_amount), func.count(Sale.id))
        .where(
            Sale.company_id == _company_id(),
            Sale.status == "completed",
            Sale.sale_date >= date_from,
            Sale.sale_date <= date_to,
        )
        .group_by(Sale.sale_date, Sale.currency)
        .order_by(Sale.sale_date, Sale.currency)
    ).all()
    daily_revenue = [
        {"date": sale_date.isoformat(), "currency": currency, "amount": str(total), "sales": count}
        for sale_date, currency, total, count in rows
    ]
    totals = {}
    for item in daily_revenue:
        currency = item["currency"]
        totals.setdefault(currency, {"currency": currency, "amount": Decimal("0.00"), "sales": 0})
        totals[currency]["amount"] += Decimal(item["amount"])
        totals[currency]["sales"] += item["sales"]
    return jsonify({
        "from": date_from.isoformat(),
        "to": date_to.isoformat(),
        "daily_revenue": daily_revenue,
        "totals_by_currency": [
            {"currency": item["currency"], "amount": str(item["amount"]), "sales": item["sales"]}
            for item in sorted(totals.values(), key=lambda value: value["currency"])
        ],
    })


@sales_bp.get("/dashboard/salespeople")
@login_required
@company_permission_required("view_dashboard")
def dashboard_salespeople(_user):
    """Return active salesperson performance for a bounded date range."""
    if g.company_membership.role not in {"admin", "manager"}:
        return jsonify({"error": "You are not allowed to view team performance."}), 403
    today = date.today()
    try:
        default_from = (today - timedelta(days=29)).isoformat()
        date_from = date.fromisoformat(request.args.get("from", default_from))
        date_to = date.fromisoformat(request.args.get("to", today.isoformat()))
        if date_from > date_to or (date_to - date_from).days > 366:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({
            "error": "Invalid dashboard date range. Choose a range of up to 367 days."
        }), 400
    company_id = _company_id()
    members = db.session.execute(
        select(User.id, User.display_name, User.email)
        .join(CompanyMembership, CompanyMembership.user_id == User.id)
        .where(CompanyMembership.company_id == company_id,
               CompanyMembership.role == "salesperson",
               CompanyMembership.status == "active")
        .order_by(User.email)
    ).all()
    rows = db.session.execute(
        select(Sale.salesperson_user_id, Sale.currency, func.sum(Sale.total_amount),
               func.count(Sale.id), func.avg(Sale.total_amount))
        .where(Sale.company_id == company_id, Sale.status == "completed",
               Sale.sale_date >= date_from, Sale.sale_date <= date_to)
        .group_by(Sale.salesperson_user_id, Sale.currency)
    ).all()
    by_seller = {}
    for seller_id, currency, revenue, count, average in rows:
        by_seller.setdefault(seller_id, []).append({
            "currency": currency, "revenue": str(revenue),
            "completed_sales": count,
            "average_sale": str(Decimal(str(average)).quantize(Decimal("0.01")) ),
        })
    return jsonify({
        "from": date_from.isoformat(), "to": date_to.isoformat(),
        "salespeople": [{
            "user_id": str(member.id), "name": member.display_name or member.email,
            "by_currency": sorted(by_seller.get(member.id, []), key=lambda item: item["currency"]),
        } for member in members],
    })


@sales_bp.get("/dashboard/summary")
@login_required
@company_permission_required("view_dashboard")
def dashboard_summary(_user):
    company_id = _company_id()
    customer_count = db.session.scalar(select(func.count()).select_from(Customer).where(
        Customer.company_id == company_id, Customer.is_active.is_(True)
    )) or 0
    product_count = db.session.scalar(select(func.count()).select_from(Product).where(
        Product.company_id == company_id, Product.is_active.is_(True)
    )) or 0
    sales_count = db.session.scalar(select(func.count()).select_from(Sale).where(
        Sale.company_id == company_id, Sale.status == "completed"
    )) or 0
    revenue_rows = db.session.execute(
        select(Sale.currency, func.sum(Sale.total_amount))
        .where(Sale.company_id == company_id, Sale.status == "completed")
        .group_by(Sale.currency)
        .order_by(Sale.currency)
    ).all()
    return jsonify({
        "customers": customer_count, "products": product_count,
        "completed_sales": sales_count,
        "revenue_by_currency": [
            {"currency": currency, "amount": str(amount)}
            for currency, amount in revenue_rows
        ],
    })
