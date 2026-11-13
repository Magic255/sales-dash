from decimal import Decimal

from argon2 import PasswordHasher

from app import create_app
from app.extensions import db
from app.models import Company, CompanyMembership, Product, User


def make_client(role="admin"):
    application = create_app({
        "TESTING": True,
        "SECRET_KEY": "sales-api-test-secret",
        "SQLALCHEMY_DATABASE_URI": "sqlite://",
        "WTF_CSRF_ENABLED": False,
        "RATELIMIT_ENABLED": False,
    })
    with application.app_context():
        db.create_all()
        user = User(
            email=f"{role}@example.test",
            password_hash=PasswordHasher().hash("a-very-strong-test-password"),
        )
        company = Company(name="Sales API Company", slug=f"sales-api-{role}")
        db.session.add_all([user, company])
        db.session.flush()
        db.session.add(CompanyMembership(
            user_id=user.id, company_id=company.id, role=role, status="active"
        ))
        company_id = str(company.id)
        db.session.commit()

    client = application.test_client()
    response = client.post("/api/auth/login", json={
        "email": f"{role}@example.test",
        "password": "a-very-strong-test-password",
    })
    assert response.status_code == 200
    selected = client.post("/api/auth/company", json={"company_id": company_id})
    assert selected.status_code == 200
    return application, client


def test_admin_can_create_customer_product_and_complete_sale():
    application, client = make_client()
    try:
        customer_response = client.post("/api/customers", json={
            "name": "  Acme Limited ",
            "email": " SALES@ACME.TEST ",
            "phone": "+255700000000",
        })
        assert customer_response.status_code == 201
        customer = customer_response.json["item"]
        assert customer["name"] == "Acme Limited"
        assert customer["email"] == "sales@acme.test"

        product_response = client.post("/api/products", json={
            "sku": " sku-001 ",
            "name": "Consulting hour",
            "unit_price": "100.50",
            "currency": "tzs",
        })
        assert product_response.status_code == 201
        product = product_response.json["item"]
        assert product["sku"] == "SKU-001"
        assert product["unit_price"] == "100.50"

        sale_response = client.post("/api/sales", json={
            "customer_id": customer["id"],
            "currency": "TZS",
            "sale_date": "2026-11-13",
            "discount_amount": "2.00",
            "tax_amount": "5.00",
            "items": [{
                "product_id": product["id"],
                "quantity": "2",
                "discount_amount": "1.00",
            }],
        })
        assert sale_response.status_code == 201
        sale = sale_response.json["item"]
        assert sale["subtotal"] == "201.00"
        assert sale["discount_amount"] == "3.00"
        assert sale["tax_amount"] == "5.00"
        assert sale["total_amount"] == "203.00"
        assert sale["items"][0]["product_name"] == "Consulting hour"

        completed = client.post(f"/api/sales/{sale['id']}/complete")
        assert completed.status_code == 200
        assert completed.json["item"]["status"] == "completed"

        summary = client.get("/api/dashboard/summary")
        assert summary.status_code == 200
        assert summary.json == {
            "customers": 1, "products": 1,
            "completed_sales": 1, "revenue_by_currency": [{"currency": "TZS", "amount": "203.00"}],
        }
        assert len(client.get("/api/sales").json["items"]) == 1
    finally:
        with application.app_context():
            db.session.remove()
            db.drop_all()


def test_salesperson_can_create_customer_and_complete_own_sale_but_not_products():
    application, client = make_client("salesperson")
    try:
        forbidden = client.post("/api/products", json={
            "sku": "SKU-1", "name": "Product", "unit_price": "10", "currency": "TZS",
        })
        assert forbidden.status_code == 403

        customer = client.post("/api/customers", json={"name": "Customer One"})
        assert customer.status_code == 201
        with application.app_context():
            user = db.session.query(User).filter_by(email="salesperson@example.test").one()
            company = db.session.query(Company).filter_by(slug="sales-api-salesperson").one()
            product = Product(
                company_id=company.id, created_by_user_id=user.id,
                sku="SELLER-ITEM", name="Seller item", unit_price=Decimal("20.00"), currency="TZS",
            )
            db.session.add(product)
            db.session.commit()
            product_id = str(product.id)
        sale = client.post("/api/sales", json={
            "customer_id": customer.json["item"]["id"],
            "currency": "TZS",
            "items": [{"product_id": product_id, "quantity": "1"}],
        })
        assert sale.status_code == 201
        completed = client.post(f"/api/sales/{sale.json['item']['id']}/complete")
        assert completed.status_code == 200
        assert completed.json["item"]["status"] == "completed"
    finally:
        with application.app_context():
            db.session.remove()
            db.drop_all()


def test_viewer_can_read_but_cannot_create_sales_records():
    application, client = make_client("viewer")
    try:
        assert client.get("/api/customers").status_code == 200
        assert client.get("/api/products").status_code == 200
        assert client.post("/api/customers", json={"name": "Blocked"}).status_code == 403
        assert client.post("/api/sales", json={}).status_code == 403
    finally:
        with application.app_context():
            db.session.remove()
            db.drop_all()


def test_sales_api_requires_login_and_selected_company():
    application = create_app({
        "TESTING": True,
        "SECRET_KEY": "sales-api-test-secret",
        "SQLALCHEMY_DATABASE_URI": "sqlite://",
        "WTF_CSRF_ENABLED": False,
        "RATELIMIT_ENABLED": False,
    })
    with application.app_context():
        db.create_all()
        try:
            client = application.test_client()
            assert client.get("/api/customers").status_code == 401
            user = User(
                email="unselected@example.test",
                password_hash=PasswordHasher().hash("a-very-strong-test-password"),
            )
            company = Company(name="Unselected", slug="unselected-company")
            db.session.add_all([user, company])
            db.session.flush()
            db.session.add(CompanyMembership(
                user_id=user.id, company_id=company.id, role="admin", status="active"
            ))
            db.session.commit()
            assert client.post("/api/auth/login", json={
                "email": "unselected@example.test",
                "password": "a-very-strong-test-password",
            }).status_code == 200
            assert client.get("/api/customers").status_code == 409
        finally:
            db.session.remove()
            db.drop_all()


def test_record_endpoints_reject_non_object_json_payloads():
    application, client = make_client()
    try:
        assert client.post("/api/customers", json=["not", "an", "object"]).status_code == 400
        assert client.post("/api/products", json=["not", "an", "object"]).status_code == 400
        assert client.post("/api/sales", json=["not", "an", "object"]).status_code == 400
    finally:
        with application.app_context():
            db.session.remove()
            db.drop_all()



def test_invalid_customer_identifier_returns_safe_validation_message():
    application, client = make_client()
    try:
        response = client.post("/api/sales", json={
            "customer_id": "NOT-A-VALID-UUID-sensitive-input",
            "currency": "TZS",
            "items": [{"product_id": "also-invalid", "quantity": "1"}],
        })
        assert response.status_code == 400
        assert response.json == {
            "error": "Invalid input. Check the submitted fields and try again."
        }
        assert "NOT-A-VALID-UUID" not in response.get_data(as_text=True)
        assert "Traceback" not in response.get_data(as_text=True)
    finally:
        with application.app_context():
            db.session.remove()
            db.drop_all()


def test_invalid_customer_and_product_fields_do_not_expose_exception_details():
    application, client = make_client()
    try:
        customer_response = client.post("/api/customers", json={
            "name": ["unexpected", "value"]
        })
        assert customer_response.status_code == 400
        assert customer_response.json == {
            "error": "Invalid input. Check the submitted fields and try again."
        }

        product_response = client.post("/api/products", json={
            "sku": "SKU-1", "name": "Product",
            "unit_price": "not-a-number-sensitive-value", "currency": "TZS",
        })
        assert product_response.status_code == 400
        assert product_response.json == {
            "error": "Invalid input. Check the submitted fields and try again."
        }
        assert "sensitive-value" not in product_response.get_data(as_text=True)
    finally:
        with application.app_context():
            db.session.remove()
            db.drop_all()



def test_admin_can_edit_draft_sale_and_report_export_is_company_scoped():
    application, client = make_client()
    try:
        customer = client.post("/api/customers", json={"name": "=Unsafe Customer"}).json["item"]
        product = client.post("/api/products", json={
            "sku": "EDIT-1", "name": "Consulting", "unit_price": "25.00", "currency": "TZS",
        }).json["item"]
        created = client.post("/api/sales", json={
            "customer_id": customer["id"], "currency": "TZS", "sale_date": "2026-11-10",
            "items": [{"product_id": product["id"], "quantity": "2"}],
        })
        assert created.status_code == 201
        sale_id = created.json["item"]["id"]

        updated = client.patch(f"/api/sales/{sale_id}", json={
            "customer_id": customer["id"], "currency": "TZS", "sale_date": "2026-11-12",
            "discount_amount": "5.00", "tax_amount": "2.00", "notes": "Revised draft",
            "items": [{"product_id": product["id"], "quantity": "3"}],
        })
        assert updated.status_code == 200
        assert updated.json["item"]["subtotal"] == "75.00"
        assert updated.json["item"]["total_amount"] == "72.00"
        assert updated.json["item"]["notes"] == "Revised draft"

        report = client.get("/api/reports/sales?from=2026-11-11&to=2026-11-13&status=draft")
        assert report.status_code == 200
        assert report.json["count"] == 1
        assert report.json["items"][0]["id"] == sale_id
        assert report.json["items"][0]["items"][0]["quantity"] == "3.000"
        assert report.json["completed_totals_by_currency"] == []

        exported = client.get("/api/reports/sales.csv?from=2026-11-11&to=2026-11-13")
        assert exported.status_code == 200
        assert exported.mimetype == "text/csv"
        assert "'=Unsafe Customer" in exported.get_data(as_text=True)
        assert exported.headers["Cache-Control"] == "no-store"
    finally:
        with application.app_context():
            db.session.remove()
            db.drop_all()


def test_completed_sales_cannot_be_edited_and_viewers_cannot_edit():
    application, client = make_client()
    try:
        customer = client.post("/api/customers", json={"name": "Customer"}).json["item"]
        product = client.post("/api/products", json={
            "sku": "LOCK-1", "name": "Product", "unit_price": "10", "currency": "TZS",
        }).json["item"]
        sale = client.post("/api/sales", json={
            "customer_id": customer["id"], "currency": "TZS",
            "items": [{"product_id": product["id"], "quantity": "1"}],
        }).json["item"]
        assert client.post(f"/api/sales/{sale['id']}/complete").status_code == 200
        response = client.patch(f"/api/sales/{sale['id']}", json={
            "customer_id": customer["id"], "currency": "TZS",
            "items": [{"product_id": product["id"], "quantity": "2"}],
        })
        assert response.status_code == 409
    finally:
        with application.app_context():
            db.session.remove()
            db.drop_all()

    viewer_app, viewer = make_client("viewer")
    try:
        response = viewer.patch("/api/sales/00000000-0000-0000-0000-000000000001", json={})
        assert response.status_code == 403
    finally:
        with viewer_app.app_context():
            db.session.remove()
            db.drop_all()


def test_sales_report_rejects_invalid_date_range():
    application, client = make_client()
    try:
        response = client.get("/api/reports/sales?from=2026-12-01&to=2026-11-01")
        assert response.status_code == 400
        assert response.json["error"] == "Invalid report filters. Check the dates and selections."
    finally:
        with application.app_context():
            db.session.remove()
            db.drop_all()
