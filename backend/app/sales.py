"""Company-scoped customer, product, sales, and dashboard APIs."""

from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from uuid import UUID, uuid4

from flask import Blueprint, g, jsonify, request, session
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from .auth import login_required
from .extensions import db
from .models import Customer, Product, Sale, SaleItem
from .permissions import company_permission_required

sales_bp = Blueprint("sales", __name__, url_prefix="/api")
CENT = Decimal("0.01")
MILLI = Decimal("0.001")


def _company_id():
    return UUID(session["company_id"])


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
        return amount.quantize(places, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        raise ValueError(f"{field.replace('_', ' ').capitalize()} is invalid.") from None


def _customer_json(item):
    return {
        "id": str(item.id), "name": item.name, "email": item.email,
        "phone": item.phone, "organization": item.organization,
        "notes": item.notes, "is_active": item.is_active,
        "created_at": item.created_at.isoformat(),
    }


def _product_json(item):
    return {
        "id": str(item.id), "sku": item.sku, "name": item.name,
        "description": item.description, "unit_price": str(item.unit_price),
        "currency": item.currency, "is_active": item.is_active,
        "created_at": item.created_at.isoformat(),
    }


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
    query = select(Customer).where(Customer.company_id == company_id)
    if request.args.get("include_inactive") != "true":
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
    data = request.get_json(silent=True) or {}
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
        db.session.commit()
    except ValueError as error:
        db.session.rollback()
        return jsonify({"error": str(error)}), 400
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "A customer with that email already exists."}), 409
    return jsonify({"item": _customer_json(item)}), 201


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
    data = request.get_json(silent=True) or {}
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
        db.session.commit()
    except ValueError as error:
        db.session.rollback()
        return jsonify({"error": str(error)}), 400
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "A customer with that email already exists."}), 409
    return jsonify({"item": _customer_json(item)})


@sales_bp.get("/products")
@login_required
@company_permission_required("view_reports")
def list_products(_user):
    company_id = _company_id()
    query = select(Product).where(Product.company_id == company_id)
    if request.args.get("include_inactive") != "true":
        query = query.where(Product.is_active.is_(True))
    search = request.args.get("search", "").strip()
    if search:
        pattern = f"%{search[:100]}%"
        query = query.where(Product.name.ilike(pattern) | Product.sku.ilike(pattern))
    items = db.session.scalars(query.order_by(Product.name).limit(100)).all()
    return jsonify({"items": [_product_json(item) for item in items]})


@sales_bp.post("/products")
@login_required
@company_permission_required("manage_products")
def create_product(user):
    data = request.get_json(silent=True) or {}
    try:
        item = Product(
            company_id=_company_id(),
            created_by_user_id=user.id,
            sku=_text(data, "sku", 64, required=True, upper=True),
            name=_text(data, "name", 160, required=True),
            description=_text(data, "description", 2000),
            unit_price=_decimal(data.get("unit_price"), "unit_price"),
            currency=_text(data, "currency", 3, required=True, upper=True),
        )
        if len(item.currency) != 3:
            raise ValueError("Currency must be a 3-letter code, such as TZS.")
        db.session.add(item)
        db.session.commit()
    except ValueError as error:
        db.session.rollback()
        return jsonify({"error": str(error)}), 400
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "That SKU already exists in this company."}), 409
    return jsonify({"item": _product_json(item)}), 201


@sales_bp.patch("/products/<uuid:product_id>")
@login_required
@company_permission_required("manage_products")
def update_product(_user, product_id):
    item = db.session.scalar(
        select(Product).where(
            Product.id == product_id, Product.company_id == _company_id()
        )
    )
    if item is None:
        return jsonify({"error": "Product not found."}), 404
    data = request.get_json(silent=True) or {}
    try:
        if "sku" in data:
            item.sku = _text(data, "sku", 64, required=True, upper=True)
        if "name" in data:
            item.name = _text(data, "name", 160, required=True)
        if "description" in data:
            item.description = _text(data, "description", 2000)
        if "unit_price" in data:
            item.unit_price = _decimal(data["unit_price"], "unit_price")
        if "currency" in data:
            item.currency = _text(data, "currency", 3, required=True, upper=True)
            if len(item.currency) != 3:
                raise ValueError("Currency must be a 3-letter code, such as TZS.")
        if "is_active" in data:
            if not isinstance(data["is_active"], bool):
                raise ValueError("is_active must be true or false.")
            item.is_active = data["is_active"]
        db.session.commit()
    except ValueError as error:
        db.session.rollback()
        return jsonify({"error": str(error)}), 400
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "That SKU already exists in this company."}), 409
    return jsonify({"item": _product_json(item)})


@sales_bp.get("/sales")
@login_required
@company_permission_required("view_reports")
def list_sales(_user):
    company_id = _company_id()
    query = (
        select(Sale, Customer.name)
        .join(Customer, (Customer.id == Sale.customer_id) & (Customer.company_id == Sale.company_id))
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
    data = request.get_json(silent=True) or {}
    company_id = _company_id()
    try:
        customer_id = UUID(str(data.get("customer_id", "")))
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
            quantity = _decimal(raw.get("quantity"), "quantity", minimum=Decimal("0.001"), places=MILLI)
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
        for product, quantity, unit_price, discount, line_total in prepared:
            db.session.add(SaleItem(
                company_id=company_id, sale_id=sale.id, product_id=product.id,
                product_name=product.name, sku_snapshot=product.sku,
                quantity=quantity, unit_price=unit_price,
                discount_amount=discount, line_total=line_total,
            ))
        db.session.commit()
    except ValueError as error:
        db.session.rollback()
        return jsonify({"error": str(error)}), 400
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "The sale could not be saved. Refresh and try again."}), 409

    return jsonify({"item": _sale_json(
        sale, customer.name,
        [{"product_name": p.name, "sku": p.sku, "quantity": str(q),
          "unit_price": str(price), "discount_amount": str(discount),
          "line_total": str(line_total)}
         for p, q, price, discount, line_total in prepared],
    )}), 201


@sales_bp.post("/sales/<uuid:sale_id>/complete")
@login_required
@company_permission_required("edit_sales")
def complete_sale(_user, sale_id):
    item = db.session.scalar(select(Sale).where(
        Sale.id == sale_id, Sale.company_id == _company_id()
    ))
    if item is None:
        return jsonify({"error": "Sale not found."}), 404
    if item.status != "draft":
        return jsonify({"error": "Only draft sales can be completed."}), 409
    item.status = "completed"
    db.session.commit()
    return jsonify({"item": _sale_json(item)})


@sales_bp.post("/sales/<uuid:sale_id>/void")
@login_required
@company_permission_required("delete_sales")
def void_sale(_user, sale_id):
    item = db.session.scalar(select(Sale).where(
        Sale.id == sale_id, Sale.company_id == _company_id()
    ))
    if item is None:
        return jsonify({"error": "Sale not found."}), 404
    if item.status == "void":
        return jsonify({"error": "This sale is already void."}), 409
    item.status = "void"
    db.session.commit()
    return jsonify({"item": _sale_json(item)})


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
    revenue = db.session.scalar(select(func.coalesce(func.sum(Sale.total_amount), 0)).where(
        Sale.company_id == company_id, Sale.status == "completed"
    )) or Decimal("0.00")
    return jsonify({
        "customers": customer_count, "products": product_count,
        "completed_sales": sales_count, "revenue": str(revenue),
    })
