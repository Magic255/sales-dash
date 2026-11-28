# ruff: noqa: I001
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from argon2 import PasswordHasher

from app import create_app
from app.extensions import db
from app.models import (
    Company, CompanyMembership, Product, PurchaseOrder, PurchaseOrderLine,
    PurchaseOrderReceipt, PurchaseOrderReceiptLine, StockBatch, StockMovement,
    Supplier, SupplierInvoice, User,
)


def _app():
    app = create_app({
        "TESTING": True,
        "SECRET_KEY": "purchase-order-test-secret",
        "SQLALCHEMY_DATABASE_URI": "sqlite://",
        "WTF_CSRF_ENABLED": False,
        "RATELIMIT_ENABLED": False,
    })
    with app.app_context():
        db.create_all()
        password = PasswordHasher().hash("synthetic-purchase-order-password")
        admin = User(email="po-admin@example.test", password_hash=password, email_verified=True)
        manager = User(email="po-manager@example.test", password_hash=password, email_verified=True)
        company = Company(name="Synthetic Retailer", slug="synthetic-retailer-po")
        db.session.add_all([admin, manager, company])
        db.session.flush()
        db.session.add_all([
            CompanyMembership(
                user_id=admin.id, company_id=company.id, role="admin", status="active"
            ),
            CompanyMembership(
                user_id=manager.id, company_id=company.id, role="manager", status="active"
            ),
        ])
        supplier = Supplier(
            company_id=company.id,
            legal_name="Synthetic Approved Supplier",
            country="TZ",
            authorised_categories=["general"],
            authorised_brands=["Synthetic Brand"],
            authorised_territories=["tz"],
            licence_number="SYNTH-LIC-001",
            licence_issuer="Synthetic Authority",
            licence_valid_until=date.today() + timedelta(days=120),
            submitted_by_user_id=admin.id,
            reviewed_by_user_id=manager.id,
            reviewed_at=datetime.now(timezone.utc),
            status="approved",
        )
        product = Product(
            company_id=company.id,
            sku="SYNTH-PO-001",
            name="Synthetic test stock",
            unit_price="20.00",
            cost_price="10.00",
            minimum_selling_price="10.00",
            currency="TZS",
            track_inventory=True,
            category_key="general",
            created_by_user_id=admin.id,
        )
        db.session.add_all([supplier, product])
        db.session.commit()
        ids = (str(company.id), str(supplier.id), str(product.id))
    return app, ids


def _login(client, company_id):
    response = client.post("/api/auth/login", json={
        "email": "po-admin@example.test",
        "password": "synthetic-purchase-order-password",
    })
    assert response.status_code == 200
    response = client.post("/api/auth/company", json={"company_id": company_id})
    assert response.status_code == 200


def _order(client, supplier_id, product_id, quantity="5.000"):
    return client.post("/api/purchase-orders", json={
        "supplier_id": supplier_id,
        "order_number": "PO-SYNTH-001",
        "currency": "TZS",
        "lines": [{
            "product_id": product_id,
            "ordered_quantity": quantity,
            "unit_cost": "10.00",
        }],
    })


def _receipt(client, order_id, line_id, delivery, quantity, batch,
             serial_reference=None, certificate_reference=None):
    line = {
        "purchase_order_line_id": line_id,
        "quantity": quantity,
        "batch_code": batch,
        "manufacturer_name": "Synthetic Manufacturer",
        "country_of_origin": "TZ",
    }
    if serial_reference:
        line["serial_reference"] = serial_reference
    if certificate_reference:
        line["certificate_reference"] = certificate_reference
    return client.post(f"/api/purchase-orders/{order_id}/receipts", json={
        "delivery_note_reference": delivery,
        "supplier_invoice_reference": "INV-SYNTH-001",
        "lines": [line],
    })


def test_purchase_order_supports_partial_receipts_and_quarantines_batches():
    app, (company_id, supplier_id, product_id) = _app()
    try:
        client = app.test_client()
        _login(client, company_id)
        created = _order(client, supplier_id, product_id)
        assert created.status_code == 201
        order = created.json["item"]
        line = order["lines"][0]
        assert order["status"] == "issued"

        first = _receipt(
            client, order["id"], line["id"], "DN-SYNTH-001", "2.000",
            "BATCH-PO-001", certificate_reference="CERT-DUP-SYNTH-001",
        )
        assert first.status_code == 201
        assert first.json["item"]["status"] == "partially_received"
        assert first.json["item"]["inventory_status"] == "quarantined_pending_compliance"

        second = _receipt(
            client, order["id"], line["id"], "DN-SYNTH-002", "3.000",
            "BATCH-PO-002", certificate_reference="CERT-DUP-SYNTH-001",
        )
        assert second.status_code == 201
        assert second.json["item"]["status"] == "received"
        assert second.json["item"]["lines"][0]["duplicate_certificate_reference"] is True
        assert second.json["purchase_order"]["lines"][0]["received_quantity"] == "5.000"

        with app.app_context():
            assert db.session.query(PurchaseOrder).one().status == "received"
            assert db.session.query(PurchaseOrderLine).one().received_quantity == 5
            assert db.session.query(PurchaseOrderReceipt).count() == 2
            assert db.session.query(PurchaseOrderReceiptLine).count() == 2
            assert db.session.query(StockMovement).filter_by(movement_type="received").count() == 2
            batches = db.session.query(StockBatch).order_by(StockBatch.batch_code).all()
            assert [batch.compliance_status for batch in batches] == [
                "pending_verification", "pending_verification",
            ]
    finally:
        with app.app_context():
            db.session.remove()
            db.drop_all()


def test_purchase_order_receipt_cannot_exceed_ordered_quantity():
    app, (company_id, supplier_id, product_id) = _app()
    try:
        client = app.test_client()
        _login(client, company_id)
        created = _order(client, supplier_id, product_id, quantity="2.000")
        order = created.json["item"]
        response = _receipt(
            client, order["id"], order["lines"][0]["id"],
            "DN-OVER-SYNTH", "2.001", "BATCH-OVER-SYNTH",
        )
        assert response.status_code == 400
        assert "exceeds the remaining" in response.json["error"]
        with app.app_context():
            assert db.session.query(PurchaseOrderReceipt).count() == 0
            assert db.session.query(StockBatch).count() == 0
            assert db.session.query(StockMovement).count() == 0
    finally:
        with app.app_context():
            db.session.remove()
            db.drop_all()


def test_purchase_order_rejects_supplier_without_approved_status():
    app, (company_id, supplier_id, product_id) = _app()
    try:
        with app.app_context():
            supplier = db.session.get(Supplier, UUID(supplier_id))
            supplier.status = "suspended"
            db.session.commit()
        client = app.test_client()
        _login(client, company_id)
        response = _order(client, supplier_id, product_id)
        assert response.status_code == 400
        assert "currently approved supplier" in response.json["error"]
        with app.app_context():
            assert db.session.query(PurchaseOrder).count() == 0
    finally:
        with app.app_context():
            db.session.remove()
            db.drop_all()

def test_duplicate_serial_number_is_rejected_across_partial_receipts():
    app, (company_id, supplier_id, product_id) = _app()
    try:
        client = app.test_client()
        _login(client, company_id)
        created = _order(client, supplier_id, product_id, quantity="2.000")
        order = created.json["item"]
        line_id = order["lines"][0]["id"]
        first = _receipt(
            client, order["id"], line_id, "DN-SERIAL-001", "1.000",
            "BATCH-SERIAL-001", serial_reference="SERIAL-SYNTH-001",
        )
        assert first.status_code == 201
        duplicate = _receipt(
            client, order["id"], line_id, "DN-SERIAL-002", "1.000",
            "BATCH-SERIAL-002", serial_reference="serial-synth-001",
        )
        assert duplicate.status_code == 409
        with app.app_context():
            assert db.session.query(StockBatch).filter(
                StockBatch.serial_reference == "SERIAL-SYNTH-001"
            ).count() == 1
            assert db.session.query(PurchaseOrderReceipt).count() == 1
            assert db.session.query(PurchaseOrderLine).one().received_quantity == 1
    finally:
        with app.app_context():
            db.session.remove()
            db.drop_all()




def _supplier_invoice(client, order_id, line_id, reference, quantity, unit_price="10.00"):
    return client.post(f"/api/purchase-orders/{order_id}/supplier-invoices", json={
        "invoice_reference": reference,
        "invoice_date": date.today().isoformat(),
        "currency": "TZS",
        "tax_amount": "0.00",
        "lines": [{
            "purchase_order_line_id": line_id,
            "quantity": quantity,
            "unit_price": unit_price,
        }],
    })


def test_supplier_invoice_three_way_match_waits_for_receipt_and_matches_price():
    app, (company_id, supplier_id, product_id) = _app()
    try:
        client = app.test_client()
        _login(client, company_id)
        created = _order(client, supplier_id, product_id, quantity="5.000")
        order = created.json["item"]
        line_id = order["lines"][0]["id"]
        received = _receipt(
            client, order["id"], line_id, "DN-INVOICE-001", "2.000",
            "BATCH-INVOICE-001",
        )
        assert received.status_code == 201

        matched = _supplier_invoice(
            client, order["id"], line_id, "INV-MATCHED-001", "2.000"
        )
        assert matched.status_code == 201
        assert matched.json["item"]["match_status"] == "matched"
        assert matched.json["item"]["subtotal"] == "20.00"
        assert matched.json["item"]["total_amount"] == "20.00"

        pending = _supplier_invoice(
            client, order["id"], line_id, "INV-PENDING-001", "3.000"
        )
        assert pending.status_code == 201
        assert pending.json["item"]["match_status"] == "pending_receipt"

        second_receipt = _receipt(
            client, order["id"], line_id, "DN-INVOICE-003", "3.000",
            "BATCH-INVOICE-003",
        )
        assert second_receipt.status_code == 201
        listed = client.get(f"/api/purchase-orders/{order['id']}/supplier-invoices")
        assert listed.status_code == 200
        assert len(listed.json["items"]) == 2
        pending_after_receipt = next(
            item for item in listed.json["items"]
            if item["invoice_reference"] == "INV-PENDING-001"
        )
        assert pending_after_receipt["match_status"] == "matched"
    finally:
        with app.app_context():
            db.session.remove()
            db.drop_all()


def test_supplier_invoice_price_variance_is_disputed_and_cumulative_overbilling_rejected():
    app, (company_id, supplier_id, product_id) = _app()
    try:
        client = app.test_client()
        _login(client, company_id)
        created = _order(client, supplier_id, product_id, quantity="2.000")
        order = created.json["item"]
        line_id = order["lines"][0]["id"]
        received = _receipt(
            client, order["id"], line_id, "DN-INVOICE-002", "2.000",
            "BATCH-INVOICE-002",
        )
        assert received.status_code == 201

        disputed = _supplier_invoice(
            client, order["id"], line_id, "INV-DISPUTED-001", "1.000", "11.00"
        )
        assert disputed.status_code == 201
        assert disputed.json["item"]["match_status"] == "disputed"

        overbilled = _supplier_invoice(
            client, order["id"], line_id, "INV-OVERBILLED-001", "2.000"
        )
        assert overbilled.status_code == 400
        assert "Cumulative invoiced quantity exceeds" in overbilled.json["error"]
        with app.app_context():
            assert db.session.query(SupplierInvoice).count() == 1
    finally:
        with app.app_context():
            db.session.remove()
            db.drop_all()


def test_supplier_invoice_rejects_client_calculated_totals_and_duplicate_reference():
    app, (company_id, supplier_id, product_id) = _app()
    try:
        client = app.test_client()
        _login(client, company_id)
        created = _order(client, supplier_id, product_id, quantity="2.000")
        order = created.json["item"]
        line_id = order["lines"][0]["id"]
        body = {
            "invoice_reference": "INV-TOTAL-001",
            "invoice_date": date.today().isoformat(),
            "currency": "TZS",
            "tax_amount": "0.00",
            "total_amount": "999.00",
            "lines": [{
                "purchase_order_line_id": line_id,
                "quantity": "1.000",
                "unit_price": "10.00",
            }],
        }
        invalid_total = client.post(
            f"/api/purchase-orders/{order['id']}/supplier-invoices", json=body
        )
        assert invalid_total.status_code == 400
        assert "server-calculated" in invalid_total.json["error"]

        body["total_amount"] = "10.00"
        created_invoice = client.post(
            f"/api/purchase-orders/{order['id']}/supplier-invoices", json=body
        )
        assert created_invoice.status_code == 201
        duplicate = client.post(
            f"/api/purchase-orders/{order['id']}/supplier-invoices", json=body
        )
        assert duplicate.status_code == 409
    finally:
        with app.app_context():
            db.session.remove()
            db.drop_all()
