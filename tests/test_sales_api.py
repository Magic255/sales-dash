from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO
from uuid import UUID

from argon2 import PasswordHasher
from cryptography.fernet import Fernet

from app import create_app
from app.extensions import db
from app.models import (
    CategoryCompliancePolicy,
    Company,
    CompanyMembership,
    Customer,
    DiscountApprovalRequest,
    Product,
    Sale,
    User,
)


def make_client(role="admin"):
    application = create_app({
        "TESTING": True,
        "SECRET_KEY": "sales-api-test-secret",
        "SQLALCHEMY_DATABASE_URI": "sqlite://",
        "WTF_CSRF_ENABLED": False,
        "RATELIMIT_ENABLED": False,
        "COMPLIANCE_EVIDENCE_ENCRYPTION_KEY": Fernet.generate_key().decode(),
    })
    with application.app_context():
        db.create_all()
        user = User(
            email=f"{role}@example.test",
            password_hash=PasswordHasher().hash("a-very-strong-test-password"),
            email_verified=True,
        )
        verifier = User(
            email="inventory-verifier@example.test",
            password_hash=PasswordHasher().hash("a-very-strong-test-password"),
            email_verified=True,
        )
        company = Company(name="Sales API Company", slug=f"sales-api-{role}")
        db.session.add_all([user, verifier, company])
        db.session.flush()
        db.session.add_all([
            CompanyMembership(
                user_id=user.id, company_id=company.id, role=role, status="active"
            ),
            CompanyMembership(
                user_id=verifier.id, company_id=company.id, role="manager", status="active"
            ),
        ])
        db.session.add(CategoryCompliancePolicy(
            company_id=company.id,
            category_key="general",
            market_country="TZ",
            approval_mode="not_required",
            accepted_authorities=[],
            requirement_source_url="https://example.test/test-category-policy",
            requirement_reference="Synthetic test policy v1",
            updated_by_user_id=user.id,
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

    original_post = client.post

    def guarded_test_post(path, *args, **kwargs):
        payload = kwargs.get("json")
        if isinstance(payload, dict) and path == "/api/products":
            payload = dict(payload)
            if not payload.get("market_country"):
                payload["market_country"] = "TZ"
            kwargs["json"] = payload
        if isinstance(payload, dict) and payload.get("movement_type") == "received":
            payload = dict(payload)
            payload.setdefault("supplier_name", "Synthetic Test Supplier")
            payload.setdefault("supplier_invoice_reference", "SYNTHETIC-INVOICE-001")
            payload.setdefault("manufacturer_name", "Synthetic Test Manufacturer")
            payload.setdefault("country_of_origin", "TZ")
            kwargs["json"] = payload
        response = original_post(path, *args, **kwargs)
        if (
            isinstance(payload, dict)
            and payload.get("movement_type") == "received"
            and response.status_code == 201
        ):
            verifier_client = application.test_client()
            verifier_login = verifier_client.post("/api/auth/login", json={
                "email": "inventory-verifier@example.test",
                "password": "a-very-strong-test-password",
            })
            assert verifier_login.status_code == 200
            verifier_selected = verifier_client.post(
                "/api/auth/company", json={"company_id": company_id}
            )
            assert verifier_selected.status_code == 200
            batch_id = response.json["item"]["batch_id"]
            evidence = verifier_client.post(
                f"/api/stock-batches/{batch_id}/evidence",
                data={"file": (
                    BytesIO(b"%PDF-1.7\\nsynthetic supplier invoice\\n"),
                    "synthetic-invoice.pdf",
                )},
                content_type="multipart/form-data",
            )
            assert evidence.status_code == 201
            released = verifier_client.post(
                f"/api/stock-batches/{batch_id}/compliance",
                json={
                    "decision": "release_not_required",
                    "notes": (
                        "Synthetic test category is configured as not requiring "
                        "authority approval."
                    ),
                    "evidence_file_id": evidence.json["item"]["id"],
                },
            )
            assert released.status_code == 200
        return response

    client.post = guarded_test_post
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
        analytics = client.get("/api/dashboard/analytics?from=2026-11-01&to=2026-11-30")
        assert analytics.status_code == 200
        assert analytics.json["from"] == "2026-11-01"
        assert analytics.json["to"] == "2026-11-30"
        assert analytics.json["daily_revenue"] == [{
            "date": "2026-11-13", "currency": "TZS", "amount": "203.00", "sales": 1,
        }]
        assert analytics.json["totals_by_currency"] == [{
            "currency": "TZS", "amount": "203.00", "sales": 1,
        }]
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


def test_manager_cannot_create_or_change_product_catalog():
    application, client = make_client("manager")
    try:
        assert client.post("/api/products", json={
            "sku": "SKU-1", "name": "Product", "unit_price": "10", "currency": "TZS",
        }).status_code == 403
        with application.app_context():
            user = db.session.query(User).filter_by(email="manager@example.test").one()
            company = db.session.query(Company).filter_by(slug="sales-api-manager").one()
            product = Product(
                company_id=company.id, created_by_user_id=user.id,
                sku="LOCKED-1", name="Original name", unit_price=Decimal("10.00"), currency="TZS",
            )
            db.session.add(product)
            db.session.commit()
            product_id = str(product.id)
        response = client.patch(f"/api/products/{product_id}", json={
            "name": "Changed name", "unit_price": "1.00",
        })
        assert response.status_code == 403
        with application.app_context():
            saved = db.session.get(Product, UUID(product_id))
            assert saved.name == "Original name"
            assert saved.unit_price == Decimal("10.00")
    finally:
        with application.app_context():
            db.session.remove()
            db.drop_all()


def test_admin_product_price_changes_are_audited_with_before_and_after_values():
    application, client = make_client("admin")
    try:
        product = client.post("/api/products", json={
            "sku": "AUDIT-1", "name": "Original", "unit_price": "10.00", "currency": "TZS",
        })
        assert product.status_code == 201
        product_id = product.json["item"]["id"]
        changed = client.patch(f"/api/products/{product_id}", json={
            "name": "Updated", "unit_price": "12.50",
        })
        assert changed.status_code == 200
        logs = client.get("/api/audit-logs?limit=20")
        assert logs.status_code == 200
        update = next(
            item for item in logs.json["items"]
            if item["event_type"] == "product_updated"
        )
        assert update["details"]["product_id"] == product_id
        assert update["details"]["old"]["unit_price"] == "10.00"
        assert update["details"]["new"]["unit_price"] == "12.50"
        assert update["details"]["old"]["name"] == "Original"
        assert update["details"]["new"]["name"] == "Updated"
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
                email_verified=True,
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
        customer = client.post("/api/customers", json={"name": " =Unsafe Customer"}).json["item"]
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


def test_dashboard_analytics_rejects_invalid_or_excessive_date_ranges():
    application, client = make_client()
    try:
        invalid = client.get("/api/dashboard/analytics?from=2026-12-01&to=2026-11-01")
        excessive = client.get("/api/dashboard/analytics?from=2025-01-01&to=2026-11-18")
        malformed = client.get("/api/dashboard/analytics?from=not-a-date")
        assert invalid.status_code == excessive.status_code == malformed.status_code == 400
        assert invalid.json == {
            "error": "Invalid dashboard date range. Choose a range of up to 367 days."
        }
    finally:
        with application.app_context():
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

def test_manager_can_archive_customers_but_cannot_change_product_catalog():
    application, client = make_client("manager")
    try:
        customer = client.post(
            "/api/customers",
            json={"name": "Archive Customer", "email": "archive@example.test"},
        ).json["item"]
        with application.app_context():
            user = db.session.query(User).filter_by(email="manager@example.test").one()
            company = db.session.query(Company).filter_by(slug="sales-api-manager").one()
            product = Product(
                company_id=company.id, created_by_user_id=user.id,
                sku="ARCHIVE-1", name="Archive Product",
                unit_price=Decimal("25.00"), currency="TZS",
            )
            db.session.add(product)
            db.session.commit()
            product_id = str(product.id)

        archived_customer = client.patch(
            f"/api/customers/{customer['id']}", json={"is_active": False}
        )
        forbidden_product_update = client.patch(
            f"/api/products/{product_id}", json={"is_active": False}
        )
        assert archived_customer.status_code == 200
        assert forbidden_product_update.status_code == 403
        assert client.get("/api/customers").json["items"] == []
        inactive_customers = client.get("/api/customers?include_inactive=true").json["items"]
        assert inactive_customers[0]["is_active"] is False
        assert len(client.get("/api/products").json["items"]) == 1

        restored_customer = client.patch(
            f"/api/customers/{customer['id']}",
            json={"name": "Updated Customer", "is_active": True},
        )
        assert restored_customer.status_code == 200
        active_customers = client.get("/api/customers").json["items"]
        assert active_customers[0]["name"] == "Updated Customer"
        with application.app_context():
            saved_product = db.session.get(Product, UUID(product_id))
            assert saved_product.name == "Archive Product"
            assert saved_product.is_active is True
    finally:
        with application.app_context():
            db.session.remove()
            db.drop_all()



def test_salesperson_cannot_list_archived_customers_or_products():
    application, client = make_client("salesperson")
    try:
        customer = client.post(
            "/api/customers", json={"name": "Archived Customer"}
        ).json["item"]
        with application.app_context():
            user = db.session.query(User).filter_by(
                email="salesperson@example.test"
            ).one()
            company = db.session.query(Company).filter_by(
                slug="sales-api-salesperson"
            ).one()
            customer_row = db.session.get(Customer, UUID(customer["id"]))
            customer_row.is_active = False
            product = Product(
                company_id=company.id,
                created_by_user_id=user.id,
                sku="ARCHIVED-ITEM",
                name="Archived item",
                unit_price=Decimal("20.00"),
                currency="TZS",
                is_active=False,
            )
            db.session.add(product)
            db.session.commit()

        assert client.get("/api/customers").status_code == 200
        assert client.get("/api/products").status_code == 200
        assert client.get("/api/customers?include_inactive=true").status_code == 403
        assert client.get("/api/products?include_inactive=true").status_code == 403
    finally:
        with application.app_context():
            db.session.remove()
            db.drop_all()


def test_manager_dashboard_shows_salesperson_performance():
    app, client = make_client()
    try:
        with app.app_context():
            manager = db.session.query(User).filter_by(email="admin@example.test").one()
            company = db.session.query(Company).filter_by(slug="sales-api-admin").one()
            seller = User(email="seller@example.test",
                password_hash=PasswordHasher().hash("a-very-strong-test-password"),
                email_verified=True)
            customer = Customer(company_id=company.id, created_by_user_id=manager.id, name="Test")
            db.session.add_all([seller, customer])
            db.session.flush()
            db.session.add(CompanyMembership(user_id=seller.id, company_id=company.id,
                role="salesperson", status="active"))
            db.session.add(Sale(company_id=company.id, sale_number="PERF-001",
                customer_id=customer.id, salesperson_user_id=seller.id,
                created_by_user_id=manager.id, status="completed", sale_date=date.today(),
                currency="TZS", total_amount=Decimal("1250.00")))
            db.session.commit()
        response = client.get("/api/dashboard/salespeople")
        assert response.status_code == 200
        seller_result = response.json["salespeople"][0]
        assert seller_result["name"] == "seller@example.test"
        assert seller_result["by_currency"] == [{
            "currency": "TZS", "revenue": "1250.00",
            "completed_sales": 1, "average_sale": "1250.00",
        }]
        invalid_range = client.get(
            "/api/dashboard/salespeople?from=2027-01-02&to=2027-01-01"
        )
        assert invalid_range.status_code == 400
    finally:
        with app.app_context():
            db.session.remove()
            db.drop_all()


def test_salesperson_cannot_view_team_performance():
    app, client = make_client("salesperson")
    try:
        assert client.get("/api/dashboard/salespeople").status_code == 403
    finally:
        with app.app_context():
            db.session.remove()
            db.drop_all()


def test_salesperson_discount_above_limit_requires_admin_approval():
    application, salesperson_client = make_client("salesperson")
    try:
        with application.app_context():
            salesperson = db.session.query(User).filter_by(
                email="salesperson@example.test"
            ).one()
            company = db.session.query(Company).filter_by(
                slug="sales-api-salesperson"
            ).one()
            customer = Customer(
                company_id=company.id, created_by_user_id=salesperson.id,
                name="Approval Customer",
            )
            product = Product(
                company_id=company.id, created_by_user_id=salesperson.id,
                sku="APPROVAL-1", name="Approval Product",
                unit_price=Decimal("100.00"), currency="TZS",
            )
            admin = User(
                email="approval-admin@example.test",
                password_hash=PasswordHasher().hash("a-very-strong-test-password"),
                email_verified=True,
            )
            db.session.add_all([customer, product, admin])
            db.session.flush()
            db.session.add(CompanyMembership(
                user_id=admin.id, company_id=company.id, role="admin", status="active"
            ))
            customer_id, product_id, company_id = customer.id, product.id, company.id
            db.session.commit()

        payload = {
            "customer_id": str(customer_id),
            "currency": "TZS",
            "items": [{
                "product_id": str(product_id), "quantity": "1",
                "discount_amount": "10.00",
            }],
        }
        missing_reason = salesperson_client.post("/api/sales", json=payload)
        assert missing_reason.status_code == 400

        payload["approval_reason"] = "Customer requested a strategic first-order discount."
        requested = salesperson_client.post("/api/sales", json=payload)
        assert requested.status_code == 201
        sale_id = requested.json["item"]["id"]
        assert salesperson_client.post(
            f"/api/sales/{sale_id}/complete"
        ).status_code == 409

        admin_client = application.test_client()
        assert admin_client.post("/api/auth/login", json={
            "email": "approval-admin@example.test",
            "password": "a-very-strong-test-password",
        }).status_code == 200
        assert admin_client.post(
            "/api/auth/company", json={"company_id": str(company_id)}
        ).status_code == 200
        inbox = admin_client.get("/api/discount-approvals")
        assert inbox.status_code == 200
        assert len(inbox.json["items"]) == 1
        approval_id = inbox.json["items"][0]["id"]
        approved = admin_client.post(
            f"/api/discount-approvals/{approval_id}/decision",
            json={"decision": "approve"},
        )
        assert approved.status_code == 200
        assert approved.json["item"]["status"] == "approved"
        completed = salesperson_client.post(f"/api/sales/{sale_id}/complete")
        assert completed.status_code == 200
        assert completed.json["item"]["status"] == "completed"

        with application.app_context():
            approval = db.session.query(DiscountApprovalRequest).one()
            assert approval.status == "approved"
            assert approval.approver_user_id is not None
    finally:
        with application.app_context():
            db.session.remove()
            db.drop_all()


def test_salesperson_cannot_view_admin_discount_approval_inbox():
    application, client = make_client("salesperson")
    try:
        assert client.get("/api/discount-approvals").status_code == 403
    finally:
        with application.app_context():
            db.session.remove()
            db.drop_all()


def test_manager_editing_salesperson_sale_uses_salesperson_discount_limit():
    application, manager_client = make_client("manager")
    try:
        with application.app_context():
            manager = db.session.query(User).filter_by(
                email="manager@example.test"
            ).one()
            company = db.session.query(Company).filter_by(
                slug="sales-api-manager"
            ).one()
            salesperson = User(
                email="credited-salesperson@example.test",
                password_hash=PasswordHasher().hash("a-very-strong-test-password"),
                email_verified=True,
            )
            customer = Customer(
                company_id=company.id, created_by_user_id=manager.id,
                name="Credited Seller Customer",
            )
            product = Product(
                company_id=company.id, created_by_user_id=manager.id,
                sku="CREDITED-SELLER-1", name="Credited Seller Product",
                unit_price=Decimal("100.00"), currency="TZS",
            )
            db.session.add_all([salesperson, customer, product])
            db.session.flush()
            db.session.add(CompanyMembership(
                user_id=salesperson.id, company_id=company.id,
                role="salesperson", status="active",
            ))
            customer_id, product_id, salesperson_id = (
                customer.id, product.id, salesperson.id
            )
            db.session.commit()

        created = manager_client.post("/api/sales", json={
            "customer_id": str(customer_id),
            "currency": "TZS",
            "items": [{"product_id": str(product_id), "quantity": "1"}],
        })
        assert created.status_code == 201
        sale_id = created.json["item"]["id"]
        with application.app_context():
            sale = db.session.get(Sale, UUID(sale_id))
            sale.salesperson_user_id = salesperson_id
            db.session.commit()

        edited = manager_client.patch(f"/api/sales/{sale_id}", json={
            "customer_id": str(customer_id),
            "currency": "TZS",
            "discount_amount": "10.00",
            "items": [{"product_id": str(product_id), "quantity": "1"}],
            "approval_reason": "Customer requested a larger discount.",
        })
        assert edited.status_code == 200
        with application.app_context():
            approval = db.session.query(DiscountApprovalRequest).one()
            assert approval.status == "pending"
            assert approval.requested_discount_percent == Decimal("10.00")
            manager = db.session.query(User).filter_by(
                email="manager@example.test"
            ).one()
            assert approval.requested_by_user_id == manager.id
        assert manager_client.post(
            f"/api/sales/{sale_id}/complete"
        ).status_code == 409
    finally:
        with application.app_context():
            db.session.remove()
            db.drop_all()


def test_product_minimum_price_requires_admin_override_reason():
    application, client = make_client("admin")
    try:
        customer = client.post("/api/customers", json={"name": "Floor Customer"}).json["item"]
        product = client.post("/api/products", json={
            "sku": "FLOOR-1", "name": "Floor Product", "unit_price": "100.00",
            "cost_price": "70.00", "minimum_selling_price": "90.00", "currency": "TZS",
        })
        assert product.status_code == 201
        invalid_catalog_price = client.post("/api/products", json={
            "sku": "FLOOR-INVALID", "name": "Invalid Floor Product",
            "unit_price": "80.00", "cost_price": "70.00",
            "minimum_selling_price": "90.00", "currency": "TZS",
        })
        assert invalid_catalog_price.status_code == 400
        item = product.json["item"]
        assert item["minimum_selling_price"] == "90.00"
        assert item["cost_price"] == "70.00"
        payload = {
            "customer_id": customer["id"], "currency": "TZS",
            "items": [{"product_id": item["id"], "quantity": "1", "discount_amount": "15.00"}],
        }
        assert client.post("/api/sales", json=payload).status_code == 400
        payload["price_floor_override_reason"] = "Approved strategic account exception."
        sale = client.post("/api/sales", json=payload)
        assert sale.status_code == 201
        logs = client.get("/api/audit-logs?limit=20")
        event = next(x for x in logs.json["items"] if x["event_type"] == "price_floor_override")
        assert event["details"]["items"][0]["effective_unit_price"] == "85.00"
        assert event["details"]["items"][0]["minimum_selling_price"] == "90.00"
    finally:
        with application.app_context():
            db.session.remove()
            db.drop_all()


def test_salesperson_is_rejected_when_discount_crosses_product_floor():
    application, client = make_client("salesperson")
    try:
        with application.app_context():
            seller = db.session.query(User).filter_by(
                email="salesperson@example.test"
            ).one()
            company = db.session.query(Company).filter_by(
                slug="sales-api-salesperson"
            ).one()
            customer = Customer(
                company_id=company.id, created_by_user_id=seller.id,
                name="Floor Guard Customer",
            )
            product = Product(
                company_id=company.id, created_by_user_id=seller.id,
                sku="FLOOR-GUARD-1", name="Floor Guard Product",
                unit_price=Decimal("100.00"), cost_price=Decimal("70.00"),
                minimum_selling_price=Decimal("90.00"), currency="TZS",
            )
            db.session.add_all([customer, product])
            db.session.commit()
            customer_id, product_id = str(customer.id), str(product.id)
        response = client.post("/api/sales", json={
            "customer_id": customer_id,
            "currency": "TZS",
            "price_floor_override_reason": "Approved exception",
            "items": [{
                "product_id": product_id, "quantity": "1",
                "discount_amount": "15.00",
            }],
        })
        assert response.status_code == 400
    finally:
        with application.app_context():
            db.session.remove()
            db.drop_all()


def test_weekly_discount_report_groups_completed_sales_by_seller_and_currency():
    application, client = make_client("admin")
    try:
        customer = client.post("/api/customers", json={"name": "Weekly Discount Customer"})
        product = client.post("/api/products", json={
            "sku": "WEEKLY-DISC-1", "name": "Weekly Discount Product",
            "unit_price": "100.00", "currency": "TZS",
        })
        assert customer.status_code == 201
        assert product.status_code == 201
        sale = client.post("/api/sales", json={
            "customer_id": customer.json["item"]["id"],
            "currency": "TZS",
            "sale_date": "2026-11-11",
            "discount_amount": "10.00",
            "items": [{"product_id": product.json["item"]["id"], "quantity": "1"}],
        })
        assert sale.status_code == 201
        completed = client.post(f"/api/sales/{sale.json['item']['id']}/complete")
        assert completed.status_code == 200

        report = client.get(
            "/api/reports/discounts/weekly?week_start=2026-11-09"
        )
        assert report.status_code == 200
        assert report.json["week_start"] == "2026-11-09"
        assert report.json["week_end"] == "2026-11-15"
        seller = report.json["salespeople"][0]
        assert seller["email"] == "admin@example.test"
        assert seller["by_currency"] == [{
            "currency": "TZS",
            "completed_sales": 1,
            "subtotal": "100.00",
            "discount_total": "10.00",
            "discount_rate_percent": "10.00",
            "net_sales_after_discount": "90.00",
        }]
        assert "does not yet track leads" in report.json["note"]
        audit = client.get("/api/audit-logs?limit=20")
        discount_event = next(
            event for event in audit.json["items"]
            if event["event_type"] == "discount_applied"
        )
        assert discount_event["details"]["old_discount_amount"] == "0.00"
        assert discount_event["details"]["new_discount_amount"] == "10.00"
        assert discount_event["details"]["items"][0]["base_unit_price"] == "100.00"
        assert discount_event["details"]["items"][0]["effective_unit_price"] == "90.00"
        invalid = client.get(
            "/api/reports/discounts/weekly?week_start=2026-11-11"
        )
        assert invalid.status_code == 400
    finally:
        with application.app_context():
            db.session.remove()
            db.drop_all()


def test_salesperson_cannot_view_weekly_team_discount_report():
    application, client = make_client("salesperson")
    try:
        response = client.get("/api/reports/discounts/weekly")
        assert response.status_code == 403
    finally:
        with application.app_context():
            db.session.remove()
            db.drop_all()


def test_completion_rechecks_current_product_floor_and_audits_admin_override():
    application, client = make_client("admin")
    try:
        customer = client.post("/api/customers", json={"name": "Recheck Floor Customer"})
        product = client.post("/api/products", json={
            "sku": "RECHECK-FLOOR-1", "name": "Recheck Floor Product",
            "unit_price": "100.00", "cost_price": "70.00",
            "minimum_selling_price": "80.00", "currency": "TZS",
        })
        assert customer.status_code == 201
        assert product.status_code == 201
        sale = client.post("/api/sales", json={
            "customer_id": customer.json["item"]["id"],
            "currency": "TZS",
            "discount_amount": "10.00",
            "items": [{"product_id": product.json["item"]["id"], "quantity": "1"}],
        })
        assert sale.status_code == 201
        changed = client.patch(
            f"/api/products/{product.json['item']['id']}",
            json={"minimum_selling_price": "95.00"},
        )
        assert changed.status_code == 200

        sale_id = sale.json["item"]["id"]
        blocked = client.post(f"/api/sales/{sale_id}/complete", json={})
        assert blocked.status_code == 400
        assert "override requires a reason" in blocked.json["error"]

        completed = client.post(f"/api/sales/{sale_id}/complete", json={
            "price_floor_override_reason": "Existing quote honoured after floor update.",
        })
        assert completed.status_code == 200
        assert completed.json["item"]["status"] == "completed"
        logs = client.get("/api/audit-logs?limit=20")
        override = next(
            event for event in logs.json["items"]
            if event["event_type"] == "price_floor_override"
        )
        assert override["details"]["reason"] == (
            "Existing quote honoured after floor update."
        )
    finally:
        with application.app_context():
            db.session.remove()
            db.drop_all()


def test_order_level_discount_cannot_bypass_product_minimum_price():
    application, client = make_client("admin")
    try:
        customer = client.post("/api/customers", json={"name": "Order Floor Customer"})
        product = client.post("/api/products", json={
            "sku": "ORDER-FLOOR-1", "name": "Order Floor Product",
            "unit_price": "100.00", "cost_price": "70.00",
            "minimum_selling_price": "90.00", "currency": "TZS",
        })
        response = client.post("/api/sales", json={
            "customer_id": customer.json["item"]["id"],
            "currency": "TZS",
            "discount_amount": "15.00",
            "items": [{"product_id": product.json["item"]["id"], "quantity": "1"}],
        })
        assert response.status_code == 400
        assert "override requires a reason" in response.json["error"]
    finally:
        with application.app_context():
            db.session.remove()
            db.drop_all()


def test_editing_draft_discount_writes_before_and_after_price_audit():
    application, client = make_client("admin")
    try:
        customer = client.post("/api/customers", json={"name": "Discount Edit Customer"})
        product = client.post("/api/products", json={
            "sku": "DISCOUNT-EDIT-1", "name": "Discount Edit Product",
            "unit_price": "100.00", "currency": "TZS",
        })
        sale = client.post("/api/sales", json={
            "customer_id": customer.json["item"]["id"],
            "currency": "TZS",
            "items": [{"product_id": product.json["item"]["id"], "quantity": "1"}],
        })
        assert sale.status_code == 201
        updated = client.patch(f"/api/sales/{sale.json['item']['id']}", json={
            "customer_id": customer.json["item"]["id"],
            "currency": "TZS",
            "discount_amount": "5.00",
            "items": [{
                "product_id": product.json["item"]["id"],
                "quantity": "1",
                "discount_amount": "0.00",
            }],
        })
        assert updated.status_code == 200
        logs = client.get("/api/audit-logs?limit=20")
        event = next(
            item for item in logs.json["items"]
            if item["event_type"] == "discount_applied"
        )
        assert event["details"]["old_discount_amount"] == "0.00"
        assert event["details"]["new_discount_amount"] == "5.00"
        assert event["details"]["items"][0]["base_unit_price"] == "100.00"
        assert event["details"]["items"][0]["effective_unit_price"] == "95.00"
    finally:
        with application.app_context():
            db.session.remove()
            db.drop_all()


def test_manager_can_view_weekly_team_discount_report():
    application, client = make_client("manager")
    try:
        response = client.get(
            "/api/reports/discounts/weekly?week_start=2026-11-23"
        )
        assert response.status_code == 200
        assert response.json["week_start"] == "2026-11-23"
        assert response.json["week_end"] == "2026-11-29"
        assert response.json["salespeople"] == []
        assert "Conversion rate is not included" in response.json["note"]
    finally:
        with application.app_context():
            db.session.remove()
            db.drop_all()


def test_weekly_discount_report_excludes_drafts_and_separates_currencies():
    application, client = make_client("admin")
    try:
        customer = client.post("/api/customers", json={"name": "Multi Currency Weekly"})
        assert customer.status_code == 201
        product_ids = {}
        for sku, currency in (("WEEK-TZS", "TZS"), ("WEEK-USD", "USD")):
            response = client.post("/api/products", json={
                "sku": sku, "name": sku, "unit_price": "100.00",
                "currency": currency,
            })
            assert response.status_code == 201
            product_ids[currency] = response.json["item"]["id"]

        for currency in ("TZS", "USD"):
            sale = client.post("/api/sales", json={
                "customer_id": customer.json["item"]["id"],
                "currency": currency,
                "sale_date": "2026-11-24",
                "discount_amount": "5.00",
                "items": [{"product_id": product_ids[currency], "quantity": "1"}],
            })
            assert sale.status_code == 201
            completed = client.post(f"/api/sales/{sale.json['item']['id']}/complete")
            assert completed.status_code == 200

        draft = client.post("/api/sales", json={
            "customer_id": customer.json["item"]["id"],
            "currency": "TZS",
            "sale_date": "2026-11-25",
            "discount_amount": "50.00",
            "items": [{"product_id": product_ids["TZS"], "quantity": "1"}],
        })
        assert draft.status_code == 201

        report = client.get(
            "/api/reports/discounts/weekly?week_start=2026-11-23"
        )
        assert report.status_code == 200
        assert len(report.json["salespeople"]) == 1
        by_currency = {
            row["currency"]: row
            for row in report.json["salespeople"][0]["by_currency"]
        }
        assert set(by_currency) == {"TZS", "USD"}
        assert by_currency["TZS"]["completed_sales"] == 1
        assert by_currency["TZS"]["discount_total"] == "5.00"
        assert by_currency["USD"]["completed_sales"] == 1
        assert by_currency["USD"]["discount_total"] == "5.00"
    finally:
        with application.app_context():
            db.session.remove()
            db.drop_all()


def test_weekly_discount_report_is_scoped_to_active_company():
    application, client = make_client("manager")
    try:
        with application.app_context():
            other_user = User(
                email="other-tenant-seller@example.test",
                email_verified=True,
            )
            other_company = Company(
                name="Other Tenant", slug="other-weekly-report-tenant"
            )
            db.session.add_all([other_user, other_company])
            db.session.flush()
            db.session.add(CompanyMembership(
                user_id=other_user.id,
                company_id=other_company.id,
                role="salesperson",
                status="active",
            ))
            other_customer = Customer(
                company_id=other_company.id,
                created_by_user_id=other_user.id,
                name="Other Tenant Customer",
            )
            db.session.add(other_customer)
            db.session.flush()
            db.session.add(Sale(
                company_id=other_company.id,
                sale_number="OTHER-WEEK-001",
                customer_id=other_customer.id,
                salesperson_user_id=other_user.id,
                created_by_user_id=other_user.id,
                status="completed",
                sale_date=date(2026, 11, 24),
                currency="TZS",
                subtotal=Decimal("1000.00"),
                discount_amount=Decimal("500.00"),
                tax_amount=Decimal("0.00"),
                total_amount=Decimal("500.00"),
            ))
            db.session.commit()

        response = client.get(
            "/api/reports/discounts/weekly?week_start=2026-11-23"
        )
        assert response.status_code == 200
        assert response.json["salespeople"] == []
    finally:
        with application.app_context():
            db.session.remove()
            db.drop_all()


def test_inventory_ledger_receives_reserves_sells_and_restores_voided_sales():
    application, client = make_client("admin")
    try:
        customer = client.post("/api/customers", json={"name": "Inventory Customer"})
        product = client.post("/api/products", json={
            "sku": "INV-LEDGER-1", "name": "Tracked Item",
            "unit_price": "100.00", "cost_price": "60.00",
            "minimum_selling_price": "80.00", "currency": "TZS",
            "track_inventory": True, "low_stock_threshold": "4.000",
        })
        assert customer.status_code == 201
        assert product.status_code == 201
        product_id = product.json["item"]["id"]
        assert product.json["item"]["track_inventory"] is True

        received = client.post(
            f"/api/products/{product_id}/stock-movements",
            json={"movement_type": "received", "quantity": "5", "batch_code": "INV-BATCH-1",
                  "reason": "Opening stock received."},
        )
        assert received.status_code == 201
        reserved = client.post(
            f"/api/products/{product_id}/stock-movements",
            json={"movement_type": "reserved", "quantity": "2",
                  "reason": "Reserved for a customer order."},
        )
        assert reserved.status_code == 201
        assert reserved.json["balance"] == {
            "stock_on_hand": "5.000",
            "reserved_quantity": "2.000",
            "available_quantity": "3.000",
        }
        low_stock = client.get("/api/inventory")
        assert low_stock.status_code == 200
        assert low_stock.json["items"][0]["status"] == "low_stock"

        insufficient = client.post("/api/sales", json={
            "customer_id": customer.json["item"]["id"], "currency": "TZS",
            "items": [{"product_id": product_id, "quantity": "4"}],
        })
        assert insufficient.status_code == 201
        blocked = client.post(
            f"/api/sales/{insufficient.json['item']['id']}/complete"
        )
        assert blocked.status_code == 409
        assert "Insufficient available stock" in blocked.json["error"]

        sale = client.post("/api/sales", json={
            "customer_id": customer.json["item"]["id"], "currency": "TZS",
            "items": [{"product_id": product_id, "quantity": "3"}],
        })
        assert sale.status_code == 201
        completed = client.post(f"/api/sales/{sale.json['item']['id']}/complete")
        assert completed.status_code == 200
        summary = client.get("/api/inventory")
        assert summary.status_code == 200
        assert summary.json["items"][0]["stock_on_hand"] == "2.000"
        assert summary.json["items"][0]["reserved_quantity"] == "2.000"
        assert summary.json["items"][0]["available_quantity"] == "0.000"
        assert summary.json["items"][0]["status"] == "reserved"

        voided = client.post(f"/api/sales/{sale.json['item']['id']}/void")
        assert voided.status_code == 200
        summary = client.get("/api/inventory")
        assert summary.json["items"][0]["stock_on_hand"] == "5.000"
        assert summary.json["items"][0]["reserved_quantity"] == "2.000"
        assert summary.json["items"][0]["available_quantity"] == "3.000"
        history = client.get(f"/api/products/{product_id}/stock-movements")
        assert history.status_code == 200
        assert [entry["movement_type"] for entry in history.json["items"]].count("sold") == 1
        assert [entry["movement_type"] for entry in history.json["items"]].count("returned") == 1
    finally:
        with application.app_context():
            db.session.remove()
            db.drop_all()


def test_manager_can_receive_stock_but_cannot_make_inventory_adjustments():
    application, client = make_client("manager")
    try:
        with application.app_context():
            manager = db.session.query(User).filter_by(
                email="manager@example.test"
            ).one()
            company = db.session.query(Company).filter_by(
                slug="sales-api-manager"
            ).one()
            product = Product(
                company_id=company.id, created_by_user_id=manager.id,
                sku="INV-MANAGER-1", name="Manager Tracked Item",
                unit_price=Decimal("50.00"), cost_price=Decimal("20.00"),
                minimum_selling_price=Decimal("30.00"),
                track_inventory=True, low_stock_threshold=Decimal("1.000"),
                currency="TZS", market_country="TZ",
            )
            db.session.add(product)
            db.session.commit()
            product_id = str(product.id)

        received = client.post(
            f"/api/products/{product_id}/stock-movements",
            json={"movement_type": "received", "quantity": "4", "batch_code": "MANAGER-BATCH-1",
                  "reason": "Supplier delivery received."},
        )
        assert received.status_code == 201
        adjustment = client.post(
            f"/api/products/{product_id}/stock-movements",
            json={"movement_type": "adjustment_decrease", "quantity": "1",
                  "reason": "Attempted correction."},
        )
        assert adjustment.status_code == 403
        summary = client.get("/api/inventory")
        assert summary.status_code == 200
        assert summary.json["items"][0]["available_quantity"] == "4.000"
    finally:
        with application.app_context():
            db.session.remove()
            db.drop_all()


def test_inventory_tracking_cannot_be_disabled_while_stock_exists():
    application, client = make_client("admin")
    try:
        product = client.post("/api/products", json={
            "sku": "INV-DISABLE-1", "name": "Inventory Locked Product",
            "unit_price": "25.00", "cost_price": "10.00",
            "minimum_selling_price": "15.00", "currency": "TZS",
            "track_inventory": True,
        })
        assert product.status_code == 201
        product_id = product.json["item"]["id"]
        received = client.post(
            f"/api/products/{product_id}/stock-movements",
            json={"movement_type": "received", "quantity": "1", "batch_code": "DISABLE-BATCH-1",
                  "reason": "Opening quantity."},
        )
        assert received.status_code == 201
        disabled = client.patch(
            f"/api/products/{product_id}",
            json={"track_inventory": False},
        )
        assert disabled.status_code == 409
        assert "cannot be disabled after stock movements" in disabled.json["error"]
    finally:
        with application.app_context():
            db.session.remove()
            db.drop_all()


def test_salesperson_cannot_access_inventory_management():
    application, client = make_client("salesperson")
    try:
        response = client.get("/api/inventory")
        assert response.status_code == 403
    finally:
        with application.app_context():
            db.session.remove()
            db.drop_all()


def test_admin_can_make_reasoned_stock_adjustments():
    application, client = make_client("admin")
    try:
        product = client.post("/api/products", json={
            "sku": "INV-ADMIN-ADJUST", "name": "Admin Adjustment Item",
            "unit_price": "40.00", "cost_price": "20.00",
            "minimum_selling_price": "25.00", "currency": "TZS",
            "track_inventory": True,
        })
        assert product.status_code == 201
        product_id = product.json["item"]["id"]
        increase = client.post(
            f"/api/products/{product_id}/stock-movements",
            json={"movement_type": "adjustment_increase", "quantity": "2",
                  "batch_code": "ADJUST-BATCH-1",
                  "supplier_name": "Synthetic Test Supplier",
                  "supplier_invoice_reference": "SYNTHETIC-INVOICE-001",
                  "manufacturer_name": "Synthetic Test Manufacturer",
                  "country_of_origin": "TZ",
                  "reason": "Physical count found two extra units."},
        )
        assert increase.status_code == 201
        decrease = client.post(
            f"/api/products/{product_id}/stock-movements",
            json={"movement_type": "adjustment_decrease", "quantity": "1",
                  "reason": "Reconciled one missing unit."},
        )
        assert decrease.status_code == 201
        assert decrease.json["balance"]["stock_on_hand"] == "1.000"
        assert decrease.json["balance"]["available_quantity"] == "0.000"
        inventory = client.get("/api/inventory").json["items"][0]
        assert inventory["quarantine_quantity"] == "1.000"
    finally:
        with application.app_context():
            db.session.remove()
            db.drop_all()


def test_inventory_batches_exclude_expired_stock_and_allocate_fifo():
    application, client = make_client("admin")
    try:
        customer = client.post("/api/customers", json={"name": "Batch FIFO Customer"})
        product = client.post("/api/products", json={
            "sku": "BATCH-FIFO-1", "name": "Batch FIFO Product",
            "unit_price": "20.00", "currency": "TZS",
            "track_inventory": True, "low_stock_threshold": "1.000",
        })
        assert customer.status_code == 201
        assert product.status_code == 201
        product_id = product.json["item"]["id"]
        yesterday = (date.today() - timedelta(days=1)).isoformat()

        expired = client.post(
            f"/api/products/{product_id}/stock-movements",
            json={
                "movement_type": "received", "quantity": "4",
                "batch_code": "EXPIRED-BATCH", "expiry_date": yesterday,
                "supplier_name": "Synthetic Test Supplier",
                "supplier_invoice_reference": "SYNTHETIC-INVOICE-001",
                "manufacturer_name": "Synthetic Test Manufacturer",
                "country_of_origin": "TZ",
                "reason": "Expired stock from synthetic test fixture.",
            },
        )
        assert expired.status_code == 201
        first = client.post(
            f"/api/products/{product_id}/stock-movements",
            json={
                "movement_type": "received", "quantity": "2",
                "batch_code": "FIFO-OLD", "expiry_date": (
                    date.today() + timedelta(days=30)
                ).isoformat(),
                "reason": "First valid delivery.",
            },
        )
        assert first.status_code == 201
        second = client.post(
            f"/api/products/{product_id}/stock-movements",
            json={
                "movement_type": "received", "quantity": "3",
                "batch_code": "FIFO-NEW", "expiry_date": (
                    date.today() + timedelta(days=90)
                ).isoformat(),
                "reason": "Second valid delivery.",
            },
        )
        assert second.status_code == 201

        summary = client.get("/api/inventory")
        item = summary.json["items"][0]
        assert item["stock_on_hand"] == "9.000"
        assert item["expired_quantity"] == "4.000"
        assert item["expiring_soon_quantity"] == "2.000"
        assert item["available_quantity"] == "5.000"
        assert item["status"] == "available"

        batches = client.get(f"/api/products/{product_id}/stock-batches")
        assert batches.status_code == 200
        batch_by_code = {row["batch_code"]: row for row in batches.json["items"]}
        assert batch_by_code["EXPIRED-BATCH"]["status"] == "expired"
        assert batch_by_code["EXPIRED-BATCH"]["available_quantity"] == "0.000"
        assert batch_by_code["FIFO-OLD"]["status"] == "expiring_soon"

        sale = client.post("/api/sales", json={
            "customer_id": customer.json["item"]["id"],
            "currency": "TZS",
            "items": [{"product_id": product_id, "quantity": "3"}],
        })
        assert sale.status_code == 201
        completed = client.post(f"/api/sales/{sale.json['item']['id']}/complete")
        assert completed.status_code == 200

        history = client.get(f"/api/products/{product_id}/stock-movements")
        sold = [row for row in history.json["items"] if row["movement_type"] == "sold"]
        sold_batch_ids = {row["batch_id"] for row in sold}
        sold_batches = client.get(f"/api/products/{product_id}/stock-batches")
        sold_by_code = {
            row["batch_code"]: row for row in sold_batches.json["items"]
        }
        assert sold_by_code["FIFO-OLD"]["status"] == "sold"
        assert sold_by_code["FIFO-NEW"]["status"] == "available"
        assert len(sold) == 2
        assert batch_by_code["EXPIRED-BATCH"]["id"] not in sold_batch_ids
        assert sum(Decimal(row["quantity"]) for row in sold) == Decimal("3.000")

        voided = client.post(f"/api/sales/{sale.json['item']['id']}/void")
        assert voided.status_code == 200
        restored = client.get(f"/api/products/{product_id}/stock-batches")
        restored_by_code = {row["batch_code"]: row for row in restored.json["items"]}
        assert restored_by_code["FIFO-OLD"]["stock_on_hand"] == "2.000"
        assert restored_by_code["FIFO-NEW"]["stock_on_hand"] == "3.000"
        assert restored_by_code["EXPIRED-BATCH"]["stock_on_hand"] == "4.000"
    finally:
        with application.app_context():
            db.session.remove()
            db.drop_all()


def test_expired_only_inventory_is_reported_and_cannot_complete_sales():
    application, client = make_client("admin")
    try:
        customer = client.post("/api/customers", json={"name": "Expired Stock Customer"})
        product = client.post("/api/products", json={
            "sku": "EXPIRED-ONLY-1", "name": "Expired Only Product",
            "unit_price": "15.00", "currency": "TZS", "track_inventory": True,
        })
        product_id = product.json["item"]["id"]
        received = client.post(
            f"/api/products/{product_id}/stock-movements",
            json={
                "movement_type": "received", "quantity": "2",
                "batch_code": "ONLY-EXPIRED",
                "supplier_name": "Synthetic Test Supplier",
                "supplier_invoice_reference": "SYNTHETIC-INVOICE-001",
                "manufacturer_name": "Synthetic Test Manufacturer",
                "country_of_origin": "TZ",
                "expiry_date": (date.today() - timedelta(days=1)).isoformat(),
                "reason": "Expired test stock.",
            },
        )
        assert received.status_code == 201
        summary = client.get("/api/inventory")
        assert summary.json["items"][0]["status"] == "expired"
        assert summary.json["items"][0]["available_quantity"] == "0.000"
        assert summary.json["items"][0]["expired_quantity"] == "2.000"
        sale = client.post("/api/sales", json={
            "customer_id": customer.json["item"]["id"],
            "currency": "TZS",
            "items": [{"product_id": product_id, "quantity": "1"}],
        })
        assert sale.status_code == 201
        blocked = client.post(f"/api/sales/{sale.json['item']['id']}/complete")
        assert blocked.status_code == 409
        assert "non-expired" in blocked.json["error"]
    finally:
        with application.app_context():
            db.session.remove()
            db.drop_all()


def test_discontinued_inventory_is_labelled_and_cannot_be_sold():
    application, client = make_client("admin")
    try:
        customer = client.post("/api/customers", json={"name": "Discontinued Customer"})
        product = client.post("/api/products", json={
            "sku": "DISCONTINUED-1", "name": "Discontinued Product",
            "unit_price": "10.00", "currency": "TZS", "track_inventory": True,
        })
        product_id = product.json["item"]["id"]
        received = client.post(
            f"/api/products/{product_id}/stock-movements",
            json={
                "movement_type": "received", "quantity": "2",
                "batch_code": "DISCONTINUED-BATCH",
                "supplier_name": "Synthetic Test Supplier",
                "supplier_invoice_reference": "SYNTHETIC-INVOICE-001",
                "manufacturer_name": "Synthetic Test Manufacturer",
                "country_of_origin": "TZ",
                "reason": "Synthetic stock receipt.",
            },
        )
        assert received.status_code == 201
        sale = client.post("/api/sales", json={
            "customer_id": customer.json["item"]["id"],
            "currency": "TZS",
            "items": [{"product_id": product_id, "quantity": "1"}],
        })
        assert sale.status_code == 201
        archived = client.patch(
            f"/api/products/{product_id}", json={"is_active": False}
        )
        assert archived.status_code == 200
        summary = client.get("/api/inventory")
        assert summary.json["items"][0]["status"] == "discontinued"
        blocked = client.post(f"/api/sales/{sale.json['item']['id']}/complete")
        assert blocked.status_code == 409
        assert "Discontinued products" in blocked.json["error"]
    finally:
        with application.app_context():
            db.session.remove()
            db.drop_all()


def test_discount_approval_notifications_are_recipient_scoped_and_readable():
    application, salesperson_client = make_client("salesperson")
    try:
        password = "a-very-strong-test-password"
        with application.app_context():
            company = db.session.query(Company).filter_by(
                slug="sales-api-salesperson"
            ).one()
            admin = User(
                email="notifications-admin@example.test",
                password_hash=PasswordHasher().hash(password),
                email_verified=True,
            )
            db.session.add(admin)
            db.session.flush()
            db.session.add(CompanyMembership(
                user_id=admin.id,
                company_id=company.id,
                role="admin",
                status="active",
            ))
            customer = Customer(
                company_id=company.id,
                created_by_user_id=admin.id,
                name="Notification Customer",
            )
            product = Product(
                company_id=company.id,
                created_by_user_id=admin.id,
                sku="NOTIFY-DISCOUNT-1",
                name="Notification Product",
                unit_price=Decimal("100.00"),
                currency="TZS",
            )
            db.session.add_all([customer, product])
            db.session.commit()
            company_id = str(company.id)
            customer_id = str(customer.id)
            product_id = str(product.id)

        admin_client = application.test_client()
        login = admin_client.post("/api/auth/login", json={
            "email": "notifications-admin@example.test",
            "password": password,
        })
        assert login.status_code == 200
        selected = admin_client.post(
            "/api/auth/company", json={"company_id": company_id}
        )
        assert selected.status_code == 200

        sale = salesperson_client.post("/api/sales", json={
            "customer_id": customer_id,
            "currency": "TZS",
            "discount_amount": "10.00",
            "approval_reason": "Customer volume discount request.",
            "items": [{"product_id": product_id, "quantity": "1"}],
        })
        assert sale.status_code == 201

        admin_notifications = admin_client.get("/api/notifications")
        assert admin_notifications.status_code == 200
        assert admin_notifications.json["unread_count"] == 1
        request_notification = admin_notifications.json["items"][0]
        assert request_notification["notification_type"] == (
            "discount_approval_requested"
        )
        assert "Notification Customer" not in request_notification["message"]
        assert "10.00%" in request_notification["message"]

        approvals = admin_client.get("/api/discount-approvals")
        assert approvals.status_code == 200
        approval_id = approvals.json["items"][0]["id"]
        decided = admin_client.post(
            f"/api/discount-approvals/{approval_id}/decision",
            json={"decision": "approve"},
        )
        assert decided.status_code == 200

        salesperson_notifications = salesperson_client.get("/api/notifications")
        assert salesperson_notifications.status_code == 200
        assert salesperson_notifications.json["unread_count"] == 1
        decision_notification = salesperson_notifications.json["items"][0]
        assert decision_notification["notification_type"] == (
            "discount_approval_decided"
        )
        assert "approved" in decision_notification["message"]

        forbidden_read = admin_client.post(
            f"/api/notifications/{decision_notification['id']}/read"
        )
        assert forbidden_read.status_code == 404
        marked = salesperson_client.post(
            f"/api/notifications/{decision_notification['id']}/read"
        )
        assert marked.status_code == 200
        refreshed = salesperson_client.get("/api/notifications")
        assert refreshed.json["unread_count"] == 0
        assert refreshed.json["items"][0]["read_at"] is not None
    finally:
        with application.app_context():
            db.session.remove()
            db.drop_all()


def test_inventory_expiry_notifications_are_deduplicated_and_role_scoped():
    application, admin_client = make_client("admin")
    try:
        password = "a-very-strong-test-password"
        with application.app_context():
            company = db.session.query(Company).filter_by(
                slug="sales-api-admin"
            ).one()
            for role in ("manager", "salesperson"):
                member = User(
                    email=f"expiry-{role}@example.test",
                    password_hash=PasswordHasher().hash(password),
                    email_verified=True,
                )
                db.session.add(member)
                db.session.flush()
                db.session.add(CompanyMembership(
                    user_id=member.id,
                    company_id=company.id,
                    role=role,
                    status="active",
                ))
            company_id = str(company.id)
            db.session.commit()

        clients = {"admin": admin_client}
        for role in ("manager", "salesperson"):
            client = application.test_client()
            login = client.post("/api/auth/login", json={
                "email": f"expiry-{role}@example.test",
                "password": password,
            })
            assert login.status_code == 200
            selected = client.post(
                "/api/auth/company", json={"company_id": company_id}
            )
            assert selected.status_code == 200
            clients[role] = client

        product = admin_client.post("/api/products", json={
            "sku": "EXPIRY-ALERT-1",
            "name": "Expiry Alert Product",
            "unit_price": "20.00",
            "currency": "TZS",
            "track_inventory": True,
        })
        assert product.status_code == 201
        product_id = product.json["item"]["id"]

        expiring = admin_client.post(
            f"/api/products/{product_id}/stock-movements",
            json={
                "movement_type": "received",
                "quantity": "5",
                "batch_code": "ALERT-EXPIRING",
                "supplier_name": "Synthetic Test Supplier",
                "supplier_invoice_reference": "SYNTHETIC-INVOICE-001",
                "manufacturer_name": "Synthetic Test Manufacturer",
                "country_of_origin": "TZ",
                "expiry_date": (date.today() + timedelta(days=30)).isoformat(),
                "reason": "Synthetic stock for expiry alert test.",
            },
        )
        expired = admin_client.post(
            f"/api/products/{product_id}/stock-movements",
            json={
                "movement_type": "received",
                "quantity": "3",
                "batch_code": "ALERT-EXPIRED",
                "supplier_name": "Synthetic Test Supplier",
                "supplier_invoice_reference": "SYNTHETIC-INVOICE-001",
                "manufacturer_name": "Synthetic Test Manufacturer",
                "country_of_origin": "TZ",
                "expiry_date": (date.today() - timedelta(days=1)).isoformat(),
                "reason": "Synthetic expired stock for alert test.",
            },
        )
        assert expiring.status_code == 201
        assert expired.status_code == 201

        depleted_product = admin_client.post("/api/products", json={
            "sku": "EXPIRY-ALERT-EMPTY",
            "name": "Depleted Expiry Product",
            "unit_price": "20.00",
            "currency": "TZS",
            "track_inventory": True,
        })
        depleted_id = depleted_product.json["item"]["id"]
        received = admin_client.post(
            f"/api/products/{depleted_id}/stock-movements",
            json={
                "movement_type": "received",
                "quantity": "2",
                "batch_code": "ALERT-EMPTY",
                "supplier_name": "Synthetic Test Supplier",
                "supplier_invoice_reference": "SYNTHETIC-INVOICE-001",
                "manufacturer_name": "Synthetic Test Manufacturer",
                "country_of_origin": "TZ",
                "expiry_date": (date.today() + timedelta(days=2)).isoformat(),
                "reason": "Synthetic stock that will be depleted.",
            },
        )
        damaged = admin_client.post(
            f"/api/products/{depleted_id}/stock-movements",
            json={
                "movement_type": "damaged",
                "quantity": "2",
                "reason": "Deplete synthetic test batch.",
            },
        )
        assert received.status_code == 201
        assert damaged.status_code == 201

        discontinued_product = admin_client.post("/api/products", json={
            "sku": "EXPIRY-ALERT-ARCHIVED",
            "name": "Discontinued Expiry Product",
            "unit_price": "20.00",
            "currency": "TZS",
            "track_inventory": True,
        })
        discontinued_id = discontinued_product.json["item"]["id"]
        archived_receipt = admin_client.post(
            f"/api/products/{discontinued_id}/stock-movements",
            json={
                "movement_type": "received",
                "quantity": "4",
                "batch_code": "ALERT-ARCHIVED",
                "supplier_name": "Synthetic Test Supplier",
                "supplier_invoice_reference": "SYNTHETIC-INVOICE-001",
                "manufacturer_name": "Synthetic Test Manufacturer",
                "country_of_origin": "TZ",
                "expiry_date": (date.today() + timedelta(days=3)).isoformat(),
                "reason": "Synthetic stock for discontinued product test.",
            },
        )
        archived = admin_client.patch(
            f"/api/products/{discontinued_id}", json={"is_active": False}
        )
        assert archived_receipt.status_code == 201
        assert archived.status_code == 200

        first_summary = admin_client.get("/api/inventory")
        second_summary = admin_client.get("/api/inventory")
        assert first_summary.status_code == 200
        assert second_summary.status_code == 200

        for role in ("admin", "manager"):
            notifications = clients[role].get("/api/notifications")
            assert notifications.status_code == 200
            assert notifications.json["unread_count"] == 2
            kinds = {
                item["notification_type"] for item in notifications.json["items"]
            }
            assert kinds == {
                "inventory_batch_expiring",
                "inventory_batch_expired",
            }
            messages = " ".join(
                item["message"] for item in notifications.json["items"]
            )
            assert "EXPIRY-ALERT-1" in messages
            assert "ALERT-EXPIRING" in messages
            assert "ALERT-EXPIRED" in messages

        salesperson_notifications = clients["salesperson"].get("/api/notifications")
        assert salesperson_notifications.status_code == 200
        assert salesperson_notifications.json["unread_count"] == 0
    finally:
        with application.app_context():
            db.session.remove()
            db.drop_all()
