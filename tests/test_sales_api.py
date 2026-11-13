from argon2 import PasswordHasher

from app import create_app
from app.extensions import db
from app.models import Company, CompanyMembership, User


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
            "completed_sales": 1, "revenue": "203.00",
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
