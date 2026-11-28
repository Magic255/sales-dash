"""Company-scoped purchase order creation and controlled partial receiving."""
# ruff: noqa: I001
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from uuid import UUID

from flask import Blueprint, jsonify, request, session
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from .audit import record_audit_event
from .auth import login_required
from .extensions import db
from .models import (
    Product,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderReceipt,
    PurchaseOrderReceiptLine,
    StockBatch,
    StockMovement,
    Supplier,
    SupplierInvoice,
    SupplierInvoiceLine,
)
from .permissions import company_permission_required


purchase_orders_bp = Blueprint("purchase_orders", __name__, url_prefix="/api")


def _company_id():
    return UUID(session["company_id"])


def _object():
    value = request.get_json(silent=True)
    return value if isinstance(value, dict) else None


def _text(value, field, limit, required=False):
    raw = value.get(field)
    if raw in (None, ""):
        if required:
            raise ValueError(f"{field.replace('_', ' ').capitalize()} is required.")
        return None
    if not isinstance(raw, str):
        raise ValueError(f"{field.replace('_', ' ').capitalize()} must be text.")
    result = raw.strip()
    if not result and required:
        raise ValueError(f"{field.replace('_', ' ').capitalize()} is required.")
    if len(result) > limit:
        raise ValueError(f"{field.replace('_', ' ').capitalize()} is too long.")
    return result or None


def _quantity(value, field, places, allow_zero=False):
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{field} must be a valid number.") from None
    if (not number.is_finite() or number < 0 or (number == 0 and not allow_zero)
            or number.as_tuple().exponent < -places):
        raise ValueError(f"{field} must be positive with at most {places} decimal places.")
    if number > Decimal("999999999.999"):
        raise ValueError(f"{field} is too large.")
    return number


def _approved_supplier(supplier):
    today = date.today()
    return (
        supplier.status == "approved"
        and supplier.licence_valid_until is not None
        and supplier.licence_valid_until >= today
        and (supplier.next_review_date is None or supplier.next_review_date >= today)
    )


def _order_json(order, lines=None):
    if lines is None:
        lines = db.session.scalars(
            select(PurchaseOrderLine).where(
                PurchaseOrderLine.company_id == order.company_id,
                PurchaseOrderLine.purchase_order_id == order.id,
            ).order_by(PurchaseOrderLine.id)
        ).all()
    return {
        "id": str(order.id),
        "supplier_id": str(order.supplier_id),
        "order_number": order.order_number,
        "status": order.status,
        "currency": order.currency,
        "notes": order.notes,
        "created_at": order.created_at.isoformat(),
        "lines": [{
            "id": str(line.id),
            "product_id": str(line.product_id),
            "ordered_quantity": str(line.ordered_quantity),
            "received_quantity": str(line.received_quantity),
            "remaining_quantity": str(line.ordered_quantity - line.received_quantity),
            "unit_cost": str(line.unit_cost),
        } for line in lines],
    }


@purchase_orders_bp.get("/purchase-orders")
@login_required
@company_permission_required("manage_inventory")
def list_purchase_orders(_user):
    company_id = _company_id()
    orders = db.session.scalars(
        select(PurchaseOrder).where(PurchaseOrder.company_id == company_id)
        .order_by(PurchaseOrder.created_at.desc(), PurchaseOrder.id.desc())
    ).all()
    return jsonify({"items": [_order_json(order) for order in orders]})


@purchase_orders_bp.post("/purchase-orders")
@login_required
@company_permission_required("manage_inventory")
def create_purchase_order(user):
    company_id = _company_id()
    data = _object()
    if data is None:
        return jsonify({"error": "Send a JSON object."}), 400
    try:
        supplier_raw = _text(data, "supplier_id", 36, required=True)
        try:
            supplier_id = UUID(supplier_raw)
        except ValueError:
            raise ValueError("Select a valid supplier.") from None
        supplier = db.session.scalar(
            select(Supplier).where(
                Supplier.id == supplier_id, Supplier.company_id == company_id
            ).with_for_update()
        )
        if supplier is None:
            return jsonify({"error": "Supplier not found."}), 404
        if not _approved_supplier(supplier):
            raise ValueError(
                "Purchase orders require an approved supplier with a current licence and review."
            )
        order_number = _text(data, "order_number", 80, required=True)
        currency = _text(data, "currency", 3, required=True).upper()
        if len(currency) != 3 or not currency.isascii() or not currency.isalpha():
            raise ValueError("Currency must be a three-letter ISO currency code.")
        notes = _text(data, "notes", 1000)
        raw_lines = data.get("lines")
        if not isinstance(raw_lines, list) or not raw_lines or len(raw_lines) > 200:
            raise ValueError("Add between 1 and 200 purchase order lines.")
        parsed = []
        seen_products = set()
        for raw in raw_lines:
            if not isinstance(raw, dict):
                raise ValueError("Each purchase order line must be an object.")
            try:
                product_id = UUID(_text(raw, "product_id", 36, required=True))
            except ValueError:
                raise ValueError("Each line must reference a valid product.") from None
            if product_id in seen_products:
                raise ValueError("A product may appear only once per purchase order.")
            seen_products.add(product_id)
            product = db.session.scalar(
                select(Product).where(
                    Product.id == product_id, Product.company_id == company_id
                ).with_for_update()
            )
            if product is None:
                raise ValueError("A purchase order product does not belong to this company.")
            if not product.is_active or not product.track_inventory:
                raise ValueError(
                    "Purchase orders can include only active inventory-tracked products."
                )
            if product.currency != currency:
                raise ValueError("Purchase order currency must match every product currency.")
            if product.category_key not in (supplier.authorised_categories or []):
                raise ValueError("Supplier is not authorised for one or more product categories.")
            quantity = _quantity(raw.get("ordered_quantity"), "ordered quantity", 3)
            unit_cost = _quantity(raw.get("unit_cost"), "unit cost", 2, allow_zero=True)
            parsed.append((product, quantity, unit_cost))
        order = PurchaseOrder(
            company_id=company_id, supplier_id=supplier.id, order_number=order_number,
            status="issued", currency=currency, notes=notes,
            created_by_user_id=user.id, created_at=datetime.now(timezone.utc),
        )
        db.session.add(order)
        db.session.flush()
        lines = [
            PurchaseOrderLine(
                company_id=company_id, purchase_order_id=order.id, product_id=product.id,
                ordered_quantity=quantity, received_quantity=Decimal("0.000"),
                unit_cost=unit_cost,
            )
            for product, quantity, unit_cost in parsed
        ]
        db.session.add_all(lines)
        db.session.flush()
        record_audit_event(
            db.session, user.id, "purchase_order_created", company_id,
            {"purchase_order_id": str(order.id), "supplier_id": str(supplier.id),
             "order_number": order.order_number, "line_count": len(lines)},
        )
        result = _order_json(order, lines)
        db.session.commit()
    except ValueError as error:
        db.session.rollback()
        return jsonify({"error": str(error)}), 400
    except IntegrityError:
        db.session.rollback()
        return jsonify({
            "error": "Purchase order number already exists or a line violates a data constraint."
        }), 409
    return jsonify({"item": result}), 201


@purchase_orders_bp.post("/purchase-orders/<uuid:purchase_order_id>/receipts")
@login_required
@company_permission_required("manage_inventory")
def receive_purchase_order(user, purchase_order_id):
    company_id = _company_id()
    data = _object()
    if data is None:
        return jsonify({"error": "Send a JSON object."}), 400
    try:
        order = db.session.scalar(
            select(PurchaseOrder).where(
                PurchaseOrder.id == purchase_order_id,
                PurchaseOrder.company_id == company_id,
            ).with_for_update()
        )
        if order is None:
            return jsonify({"error": "Purchase order not found."}), 404
        if order.status in {"received", "cancelled"}:
            raise ValueError("This purchase order cannot accept further receipts.")
        supplier = db.session.scalar(
            select(Supplier).where(
                Supplier.id == order.supplier_id, Supplier.company_id == company_id
            ).with_for_update()
        )
        if supplier is None or not _approved_supplier(supplier):
            raise ValueError("The supplier is no longer approved for new stock receipts.")
        delivery_note = _text(data, "delivery_note_reference", 120, required=True)
        invoice = _text(data, "supplier_invoice_reference", 120)
        raw_lines = data.get("lines")
        if not isinstance(raw_lines, list) or not raw_lines or len(raw_lines) > 200:
            raise ValueError("Add at least one receipt line.")
        order_lines = db.session.scalars(
            select(PurchaseOrderLine).where(
                PurchaseOrderLine.company_id == company_id,
                PurchaseOrderLine.purchase_order_id == order.id,
            ).with_for_update()
        ).all()
        by_id = {line.id: line for line in order_lines}
        seen = set()
        seen_certificate_refs = set()
        parsed = []
        for raw in raw_lines:
            if not isinstance(raw, dict):
                raise ValueError("Each receipt line must be an object.")
            try:
                line_id = UUID(_text(raw, "purchase_order_line_id", 36, required=True))
            except ValueError:
                raise ValueError("Each receipt line must reference a valid order line.") from None
            if line_id in seen:
                raise ValueError("A purchase order line may appear only once in a receipt.")
            seen.add(line_id)
            line = by_id.get(line_id)
            if line is None:
                raise ValueError("Receipt line does not belong to this purchase order.")
            quantity = _quantity(raw.get("quantity"), "received quantity", 3)
            if line.received_quantity + quantity > line.ordered_quantity:
                raise ValueError("Received quantity exceeds the remaining purchase order quantity.")
            product = db.session.scalar(
                select(Product).where(
                    Product.id == line.product_id, Product.company_id == company_id
                ).with_for_update()
            )
            if product is None or not product.is_active or not product.track_inventory:
                raise ValueError("The ordered product is unavailable for inventory receiving.")
            if product.category_key not in (supplier.authorised_categories or []):
                raise ValueError("Supplier authorisation no longer covers this product category.")
            batch_code = _text(raw, "batch_code", 80, required=True)
            serial_reference = _text(raw, "serial_reference", 160)
            serial_reference = serial_reference.upper() if serial_reference else None
            certificate_reference = _text(raw, "certificate_reference", 160)
            certificate_reference = certificate_reference.upper() if certificate_reference else None
            if serial_reference and quantity != Decimal("1.000"):
                raise ValueError(
                    "A serial-numbered receipt line must have a quantity of exactly one."
                )
            duplicate_certificate = False
            if certificate_reference:
                duplicate_certificate = (
                    certificate_reference in seen_certificate_refs
                    or db.session.scalar(
                        select(StockBatch.id).where(
                            StockBatch.company_id == company_id,
                            StockBatch.certificate_reference == certificate_reference,
                        ).limit(1)
                    ) is not None
                )
                seen_certificate_refs.add(certificate_reference)
            manufacturer = _text(raw, "manufacturer_name", 160, required=True)
            origin = _text(raw, "country_of_origin", 2, required=True).upper()
            if len(origin) != 2 or not origin.isascii() or not origin.isalpha():
                raise ValueError(
                    "Country of origin must be a two-letter ISO country code."
                )
            authorised_origins = {
                str(value).lower() for value in (supplier.authorised_territories or [])
            }
            if origin.lower() not in authorised_origins:
                raise ValueError("Supplier is not authorised for this country of origin.")
            expiry_raw = raw.get("expiry_date")
            if expiry_raw in (None, ""):
                expiry = None
            elif isinstance(expiry_raw, str):
                try:
                    expiry = date.fromisoformat(expiry_raw)
                except ValueError:
                    raise ValueError("Expiry date must use YYYY-MM-DD.") from None
            else:
                raise ValueError("Expiry date must use YYYY-MM-DD.")
            parsed.append((
                line, product, quantity, batch_code, serial_reference,
                certificate_reference, duplicate_certificate, manufacturer, origin, expiry,
            ))
        receipt = PurchaseOrderReceipt(
            company_id=company_id, purchase_order_id=order.id, supplier_id=supplier.id,
            delivery_note_reference=delivery_note, supplier_invoice_reference=invoice,
            received_by_user_id=user.id, received_at=datetime.now(timezone.utc),
        )
        db.session.add(receipt)
        db.session.flush()
        receipt_items = []
        movements = []
        for (
            line, product, quantity, batch_code, serial_reference,
            certificate_reference, duplicate_certificate, manufacturer, origin, expiry,
        ) in parsed:
            batch = StockBatch(
                company_id=company_id, product_id=product.id, batch_code=batch_code,
                expiry_date=expiry, serial_reference=serial_reference,
                supplier_id=supplier.id, supplier_name=supplier.legal_name,
                supplier_invoice_reference=invoice, delivery_note_reference=delivery_note,
                manufacturer_name=manufacturer, country_of_origin=origin,
                certificate_reference=certificate_reference,
                verification_notes=(
                    "Duplicate certificate reference detected; independent issuer/registry "
                    "verification required."
                    if duplicate_certificate else None
                ),
                compliance_status="pending_verification", received_by_user_id=user.id,
                created_at=datetime.now(timezone.utc),
            )
            db.session.add(batch)
            db.session.flush()
            receipt_items.append(PurchaseOrderReceiptLine(
                company_id=company_id, receipt_id=receipt.id,
                purchase_order_line_id=line.id, batch_id=batch.id, quantity=quantity,
            ))
            movements.append(StockMovement(
                company_id=company_id, product_id=product.id, batch_id=batch.id,
                actor_user_id=user.id, movement_type="received", quantity=quantity,
                reason=f"Purchase order {order.order_number} receipt",
                reference=delivery_note,
            ))
            line.received_quantity += quantity
        db.session.add_all(receipt_items + movements)
        order.status = (
            "received"
            if all(
                line.received_quantity == line.ordered_quantity for line in order_lines
            )
            else "partially_received"
        )
        db.session.flush()
        record_audit_event(
            db.session, user.id, "purchase_order_receipt_recorded", company_id,
            {"purchase_order_id": str(order.id), "receipt_id": str(receipt.id),
             "supplier_id": str(supplier.id), "delivery_note_reference": delivery_note,
             "line_count": len(receipt_items), "status": order.status,
             "batches": [str(item.batch_id) for item in receipt_items]},
        )
        result = {
            "id": str(receipt.id), "purchase_order_id": str(order.id),
            "delivery_note_reference": delivery_note, "status": order.status,
            "lines": [{
                "purchase_order_line_id": str(item.purchase_order_line_id),
                "batch_id": str(item.batch_id), "quantity": str(item.quantity),
                "serial_reference": next(
                    (
                        entry[4] for entry in parsed
                        if entry[0].id == item.purchase_order_line_id
                    ),
                    None,
                ),
                "certificate_reference": next(
                    (
                        entry[5] for entry in parsed
                        if entry[0].id == item.purchase_order_line_id
                    ),
                    None,
                ),
                "duplicate_certificate_reference": next(
                    (
                        entry[6] for entry in parsed
                        if entry[0].id == item.purchase_order_line_id
                    ),
                    False,
                ),
            } for item in receipt_items],
            "inventory_status": "quarantined_pending_compliance",
        }
        db.session.commit()
    except ValueError as error:
        db.session.rollback()
        return jsonify({"error": str(error)}), 400
    except IntegrityError:
        db.session.rollback()
        return jsonify({
            "error": "Duplicate delivery note, batch code or invalid receipt reference."
        }), 409
    return jsonify({"item": result, "purchase_order": _order_json(order)}), 201



def _supplier_invoice_json(invoice):
    lines = db.session.scalars(
        select(SupplierInvoiceLine).where(
            SupplierInvoiceLine.company_id == invoice.company_id,
            SupplierInvoiceLine.invoice_id == invoice.id,
        ).order_by(SupplierInvoiceLine.id)
    ).all()
    return {
        "id": str(invoice.id),
        "purchase_order_id": str(invoice.purchase_order_id),
        "supplier_id": str(invoice.supplier_id),
        "invoice_reference": invoice.invoice_reference,
        "invoice_date": invoice.invoice_date.isoformat(),
        "currency": invoice.currency,
        "subtotal": str(invoice.subtotal),
        "tax_amount": str(invoice.tax_amount),
        "total_amount": str(invoice.total_amount),
        "match_status": invoice.match_status,
        "lines": [{
            "purchase_order_line_id": str(line.purchase_order_line_id),
            "quantity": str(line.quantity),
            "unit_price": str(line.unit_price),
            "line_total": str(line.line_total),
        } for line in lines],
    }


@purchase_orders_bp.get("/purchase-orders/<uuid:order_id>/supplier-invoices")
@login_required
@company_permission_required("manage_inventory")
def list_supplier_invoices(_user, order_id):
    company_id = _company_id()
    order = db.session.scalar(select(PurchaseOrder).where(
        PurchaseOrder.id == order_id, PurchaseOrder.company_id == company_id
    ))
    if order is None:
        return jsonify({"error": "Purchase order not found."}), 404
    invoices = db.session.scalars(
        select(SupplierInvoice).where(
            SupplierInvoice.company_id == company_id,
            SupplierInvoice.purchase_order_id == order.id,
        ).order_by(SupplierInvoice.invoice_date.desc(), SupplierInvoice.created_at.desc())
    ).all()
    return jsonify({"items": [_supplier_invoice_json(item) for item in invoices]})


@purchase_orders_bp.post("/purchase-orders/<uuid:order_id>/supplier-invoices")
@login_required
@company_permission_required("manage_inventory")
def record_supplier_invoice(user, order_id):
    company_id = _company_id()
    data = _object()
    if data is None:
        return jsonify({"error": "Send a JSON object."}), 400
    try:
        order = db.session.scalar(select(PurchaseOrder).where(
            PurchaseOrder.id == order_id, PurchaseOrder.company_id == company_id
        ).with_for_update())
        if order is None:
            return jsonify({"error": "Purchase order not found."}), 404
        supplier = db.session.scalar(select(Supplier).where(
            Supplier.id == order.supplier_id, Supplier.company_id == company_id
        ).with_for_update())
        if supplier is None:
            return jsonify({"error": "Supplier not found."}), 404

        invoice_reference = _text(data, "invoice_reference", 120, required=True)
        currency = _text(data, "currency", 3, required=True).upper()
        if currency != order.currency:
            raise ValueError("Supplier invoice currency must match the purchase order currency.")
        try:
            invoice_date = date.fromisoformat(_text(data, "invoice_date", 10, required=True))
        except ValueError:
            raise ValueError("Invoice date must use YYYY-MM-DD.") from None
        tax_amount = _quantity(data.get("tax_amount", "0"), "tax amount", 2, allow_zero=True)
        raw_lines = data.get("lines")
        if not isinstance(raw_lines, list) or not raw_lines or len(raw_lines) > 200:
            raise ValueError("Add between 1 and 200 supplier invoice lines.")

        order_lines = db.session.scalars(select(PurchaseOrderLine).where(
            PurchaseOrderLine.company_id == company_id,
            PurchaseOrderLine.purchase_order_id == order.id,
        ).with_for_update()).all()
        by_id = {line.id: line for line in order_lines}
        seen = set()
        parsed = []
        subtotal = Decimal("0.00")
        has_price_variance = False
        has_unreceived_quantity = False
        for raw in raw_lines:
            if not isinstance(raw, dict):
                raise ValueError("Each supplier invoice line must be an object.")
            try:
                line_id = UUID(_text(raw, "purchase_order_line_id", 36, required=True))
            except ValueError:
                raise ValueError("Each invoice line must reference a valid purchase-order line.") from None
            if line_id in seen:
                raise ValueError("A purchase-order line may appear only once per invoice.")
            seen.add(line_id)
            order_line = by_id.get(line_id)
            if order_line is None:
                raise ValueError("Invoice line does not belong to this purchase order.")
            quantity = _quantity(raw.get("quantity"), "invoiced quantity", 3)
            unit_price = _quantity(raw.get("unit_price"), "invoice unit price", 2, allow_zero=True)
            already_invoiced = db.session.scalar(
                select(func.coalesce(func.sum(SupplierInvoiceLine.quantity), 0))
                .join(SupplierInvoice, SupplierInvoice.id == SupplierInvoiceLine.invoice_id)
                .where(
                    SupplierInvoiceLine.company_id == company_id,
                    SupplierInvoiceLine.purchase_order_line_id == order_line.id,
                )
            )
            if Decimal(str(already_invoiced or 0)) + quantity > order_line.ordered_quantity:
                raise ValueError("Cumulative invoiced quantity exceeds the purchase-order quantity.")
            if unit_price != order_line.unit_cost:
                has_price_variance = True
            if quantity > order_line.received_quantity:
                has_unreceived_quantity = True
            line_total = (quantity * unit_price).quantize(Decimal("0.01"))
            subtotal += line_total
            parsed.append((order_line, quantity, unit_price, line_total))

        declared_subtotal = data.get("subtotal")
        if declared_subtotal not in (None, ""):
            supplied = _quantity(declared_subtotal, "invoice subtotal", 2, allow_zero=True)
            if supplied != subtotal:
                raise ValueError("Invoice subtotal must equal the server-calculated line total.")
        total_amount = (subtotal + tax_amount).quantize(Decimal("0.01"))
        declared_total = data.get("total_amount")
        if declared_total not in (None, ""):
            supplied_total = _quantity(declared_total, "invoice total", 2, allow_zero=True)
            if supplied_total != total_amount:
                raise ValueError("Invoice total must equal the server-calculated subtotal plus tax.")

        match_status = (
            "disputed" if has_price_variance
            else "pending_receipt" if has_unreceived_quantity
            else "matched"
        )
        invoice = SupplierInvoice(
            company_id=company_id,
            purchase_order_id=order.id,
            supplier_id=supplier.id,
            invoice_reference=invoice_reference,
            invoice_date=invoice_date,
            currency=currency,
            subtotal=subtotal,
            tax_amount=tax_amount,
            total_amount=total_amount,
            match_status=match_status,
            created_by_user_id=user.id,
        )
        db.session.add(invoice)
        db.session.flush()
        db.session.add_all([
            SupplierInvoiceLine(
                company_id=company_id,
                invoice_id=invoice.id,
                purchase_order_line_id=line.id,
                quantity=quantity,
                unit_price=unit_price,
                line_total=line_total,
            )
            for line, quantity, unit_price, line_total in parsed
        ])
        record_audit_event(
            db.session, user.id, "supplier_invoice_recorded", company_id,
            {
                "purchase_order_id": str(order.id),
                "supplier_invoice_id": str(invoice.id),
                "supplier_id": str(supplier.id),
                "invoice_reference": invoice.invoice_reference,
                "match_status": match_status,
                "total_amount": str(total_amount),
                "currency": currency,
            },
        )
        result = _supplier_invoice_json(invoice)
        db.session.commit()
    except ValueError as error:
        db.session.rollback()
        return jsonify({"error": str(error)}), 400
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "Supplier invoice reference already exists for this supplier."}), 409
    return jsonify({"item": result}), 201
