"""Company-scoped inventory batches, balances, and immutable stock movements."""

from datetime import date
from decimal import Decimal, InvalidOperation
from uuid import UUID

from flask import Blueprint, g, jsonify, request, session
from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError

from .auth import login_required
from .extensions import db
from .models import Product, ProductBatch, StockMovement
from .permissions import company_permission_required

inventory_bp = Blueprint("inventory", __name__, url_prefix="/api/inventory")
ZERO = Decimal("0.000")


def _company_id():
    return UUID(session["company_id"])


def _json_object():
    value = request.get_json(silent=True)
    return value if isinstance(value, dict) else None


def _decimal(value, field, *, allow_negative=False):
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{field} must be a valid number.") from None
    if not number.is_finite() or (not allow_negative and number <= 0):
        raise ValueError(f"{field} must be greater than zero.")
    return number.quantize(Decimal("0.001"))


def _text(data, field, maximum, *, required=True):
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
    return value or None


def batch_balance(company_id, batch_id):
    """Return (on-hand, reserved) for a batch from its immutable movement ledger."""
    on_hand, reserved = db.session.execute(
        select(
            func.coalesce(func.sum(StockMovement.quantity_delta), 0),
            func.coalesce(func.sum(StockMovement.reserved_delta), 0),
        ).where(
            StockMovement.company_id == company_id,
            StockMovement.batch_id == batch_id,
        )
    ).one()
    return Decimal(str(on_hand)), Decimal(str(reserved))


def record_sale_stock_movements(session_company_id, sale, user, *, returning=False):
    """Consume or restore tracked sale quantities while holding product/batch locks."""
    from .models import SaleItem

    lines = db.session.scalars(
        select(SaleItem).where(
            SaleItem.company_id == session_company_id,
            SaleItem.sale_id == sale.id,
        ).order_by(SaleItem.product_id, SaleItem.batch_id)
    ).all()
    for line in lines:
        product = db.session.scalar(
            select(Product).where(
                Product.company_id == session_company_id,
                Product.id == line.product_id,
            ).with_for_update()
        )
        if product is None:
            raise ValueError("A product on this sale could not be checked for stock.")
        if not product.track_inventory:
            continue
        if line.batch_id is None:
            raise ValueError(
                f"Choose an inventory batch for tracked product {product.sku}."
            )
        batch = db.session.scalar(
            select(ProductBatch).where(
                ProductBatch.company_id == session_company_id,
                ProductBatch.id == line.batch_id,
                ProductBatch.product_id == product.id,
            ).with_for_update()
        )
        if batch is None:
            raise ValueError("The selected product batch could not be found.")
        on_hand, reserved = batch_balance(session_company_id, batch.id)
        if returning:
            quantity_delta = line.quantity
            movement_type = "returned"
            reason = f"Stock restored from voided sale {sale.sale_number}."
        else:
            if batch.expiry_date and batch.expiry_date < date.today():
                raise ValueError(f"Batch {batch.batch_code} has expired.")
            available = on_hand - reserved
            if available < line.quantity:
                raise ValueError(
                    f"Insufficient available stock in batch {batch.batch_code}."
                )
            quantity_delta = -line.quantity
            movement_type = "sold"
            reason = f"Stock issued for sale {sale.sale_number}."
        db.session.add(StockMovement(
            company_id=session_company_id,
            product_id=product.id,
            batch_id=batch.id,
            sale_id=sale.id,
            actor_user_id=user.id,
            movement_type=movement_type,
            quantity_delta=quantity_delta,
            reserved_delta=Decimal("0.000"),
            reason=reason,
        ))


def _inventory_rows(company_id):
    products = db.session.scalars(
        select(Product).where(Product.company_id == company_id).order_by(Product.name)
    ).all()
    product_ids = [product.id for product in products]
    batches = db.session.scalars(
        select(ProductBatch)
        .where(
            ProductBatch.company_id == company_id,
            ProductBatch.product_id.in_(product_ids),
        )
        .order_by(ProductBatch.batch_code)
    ).all() if product_ids else []
    balances = db.session.execute(
        select(
            StockMovement.batch_id,
            func.coalesce(func.sum(StockMovement.quantity_delta), 0),
            func.coalesce(func.sum(StockMovement.reserved_delta), 0),
            func.coalesce(func.sum(case(
                (StockMovement.movement_type == "sold", -StockMovement.quantity_delta),
                else_=0,
            )), 0),
        )
        .where(StockMovement.company_id == company_id)
        .group_by(StockMovement.batch_id)
    ).all()
    by_batch = {
        batch_id: (
            Decimal(str(on_hand)),
            Decimal(str(reserved)),
            Decimal(str(sold)),
        )
        for batch_id, on_hand, reserved, sold in balances
    }
    by_product = {}
    for batch in batches:
        on_hand, reserved, sold = by_batch.get(batch.id, (ZERO, ZERO, ZERO))
        by_product.setdefault(batch.product_id, []).append({
            "id": str(batch.id),
            "batch_code": batch.batch_code,
            "expiry_date": batch.expiry_date.isoformat() if batch.expiry_date else None,
            "on_hand": on_hand,
            "reserved": reserved,
            "sold": sold,
        })
    result = []
    today = date.today()
    for product in products:
        product_batches = by_product.get(product.id, [])
        on_hand = sum((batch["on_hand"] for batch in product_batches), ZERO)
        reserved = sum((batch["reserved"] for batch in product_batches), ZERO)
        expired_stock = sum((
            batch["on_hand"] for batch in product_batches
            if batch["expiry_date"] and date.fromisoformat(batch["expiry_date"]) < today
        ), ZERO)
        available = sum((
            max(batch["on_hand"] - batch["reserved"], ZERO)
            for batch in product_batches
            if not batch["expiry_date"] or date.fromisoformat(batch["expiry_date"]) >= today
        ), ZERO)
        sold = sum((batch["sold"] for batch in product_batches), ZERO)
        if not product.is_active:
            status = "Discontinued"
        elif on_hand <= 0 and sold > 0:
            status = "Sold"
        elif on_hand <= 0:
            status = "Out of stock"
        elif expired_stock >= on_hand:
            status = "Expired"
        elif available <= 0 and reserved > 0:
            status = "Reserved"
        elif available <= product.reorder_level:
            status = "Low stock"
        else:
            status = "Available"
        result.append({
            "product_id": str(product.id),
            "sku": product.sku,
            "name": product.name,
            "track_inventory": product.track_inventory,
            "reorder_level": str(product.reorder_level),
            "on_hand": str(on_hand),
            "reserved": str(reserved),
            "available": str(available),
            "status": status if product.track_inventory else "Not tracked",
            "batches": [{
                **batch,
                "on_hand": str(batch["on_hand"]),
                "reserved": str(batch["reserved"]),
                "sold": str(batch["sold"]),
            } for batch in product_batches],
        })
    return result


@inventory_bp.get("")
@login_required
@company_permission_required("view_reports")
def inventory_summary(_user):
    return jsonify({"items": _inventory_rows(_company_id())})


@inventory_bp.get("/movements")
@login_required
@company_permission_required("view_reports")
def inventory_movements(_user):
    company_id = _company_id()
    rows = db.session.execute(
        select(StockMovement, Product.name, Product.sku, ProductBatch.batch_code)
        .join(Product, (Product.id == StockMovement.product_id)
              & (Product.company_id == StockMovement.company_id))
        .join(ProductBatch, (ProductBatch.id == StockMovement.batch_id)
              & (ProductBatch.company_id == StockMovement.company_id))
        .where(StockMovement.company_id == company_id)
        .order_by(StockMovement.created_at.desc())
        .limit(200)
    ).all()
    return jsonify({"items": [{
        "id": str(movement.id),
        "product_name": product_name,
        "sku": sku,
        "batch_code": batch_code,
        "movement_type": movement.movement_type,
        "quantity_delta": str(movement.quantity_delta),
        "reserved_delta": str(movement.reserved_delta),
        "reason": movement.reason,
        "created_at": movement.created_at.isoformat(),
    } for movement, product_name, sku, batch_code in rows]})


@inventory_bp.post("/batches")
@login_required
@company_permission_required("manage_inventory")
def create_inventory_batch(user):
    data = _json_object()
    if data is None:
        return jsonify({"error": "Send a JSON object."}), 400
    company_id = _company_id()
    try:
        product_id = UUID(str(data.get("product_id", "")))
        product = db.session.scalar(
            select(Product).where(
                Product.company_id == company_id,
                Product.id == product_id,
            ).with_for_update()
        )
        if product is None or not product.track_inventory:
            raise ValueError("Choose a product with inventory tracking enabled.")
        batch_code = _text(data, "batch_code", 80)
        expiry_value = _text(data, "expiry_date", 10, required=False)
        expiry_date = date.fromisoformat(expiry_value) if expiry_value else None
        batch = ProductBatch(
            company_id=company_id,
            product_id=product.id,
            batch_code=batch_code,
            expiry_date=expiry_date,
            created_by_user_id=user.id,
        )
        db.session.add(batch)
        db.session.commit()
    except (ValueError, TypeError):
        db.session.rollback()
        return jsonify({"error": "Invalid batch details. Check the product, code, and expiry date."}), 400
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "That batch code already exists for this product."}), 409
    return jsonify({"item": {
        "id": str(batch.id),
        "product_id": str(batch.product_id),
        "batch_code": batch.batch_code,
        "expiry_date": batch.expiry_date.isoformat() if batch.expiry_date else None,
    }}), 201


@inventory_bp.post("/movements")
@login_required
@company_permission_required("manage_inventory")
def create_inventory_movement(user):
    data = _json_object()
    if data is None:
        return jsonify({"error": "Send a JSON object."}), 400
    company_id = _company_id()
    try:
        product_id = UUID(str(data.get("product_id", "")))
        batch_id = UUID(str(data.get("batch_id", "")))
        product = db.session.scalar(
            select(Product).where(
                Product.company_id == company_id,
                Product.id == product_id,
            ).with_for_update()
        )
        batch = db.session.scalar(
            select(ProductBatch).where(
                ProductBatch.company_id == company_id,
                ProductBatch.id == batch_id,
                ProductBatch.product_id == product_id,
            ).with_for_update()
        )
        if product is None or not product.track_inventory or batch is None:
            raise ValueError("Choose a valid tracked product and one of its batches.")
        movement_type = _text(data, "movement_type", 20)
        reason = _text(data, "reason", 1000)
        if movement_type not in {
            "received", "returned", "damaged", "adjusted", "reserved", "released"
        }:
            raise ValueError("Choose a supported stock movement.")
        if movement_type == "adjusted" and g.company_membership.role != "admin":
            db.session.rollback()
            return jsonify({"error": "Only an Admin can make stock adjustments."}), 403
        on_hand, reserved = batch_balance(company_id, batch.id)
        quantity_delta = Decimal("0.000")
        reserved_delta = Decimal("0.000")
        if movement_type == "adjusted":
            quantity_delta = _decimal(data.get("quantity_delta"), "quantity_delta", allow_negative=True)
            if quantity_delta == 0:
                raise ValueError("quantity_delta cannot be zero.")
        else:
            quantity = _decimal(data.get("quantity"), "quantity")
            if movement_type in {"received", "returned"}:
                quantity_delta = quantity
            elif movement_type == "damaged":
                quantity_delta = -quantity
            elif movement_type == "reserved":
                reserved_delta = quantity
            elif movement_type == "released":
                reserved_delta = -quantity
        if movement_type == "received" and batch.expiry_date and batch.expiry_date < date.today():
            raise ValueError("Cannot receive stock into an expired batch.")
        new_on_hand = on_hand + quantity_delta
        new_reserved = reserved + reserved_delta
        if new_on_hand < 0 or new_reserved < 0 or new_reserved > new_on_hand:
            raise ValueError("This movement would make stock or reservations invalid.")
        movement = StockMovement(
            company_id=company_id,
            product_id=product_id,
            batch_id=batch_id,
            actor_user_id=user.id,
            movement_type=movement_type,
            quantity_delta=quantity_delta,
            reserved_delta=reserved_delta,
            reason=reason,
        )
        db.session.add(movement)
        db.session.commit()
    except (ValueError, TypeError):
        db.session.rollback()
        return jsonify({"error": "Invalid stock movement. Check the quantity, batch, and reason."}), 400
    return jsonify({
        "item": {
            "id": str(movement.id),
            "movement_type": movement.movement_type,
            "quantity_delta": str(movement.quantity_delta),
            "reserved_delta": str(movement.reserved_delta),
            "reason": movement.reason,
        },
        "inventory": _inventory_rows(company_id),
    }), 201
