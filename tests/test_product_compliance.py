from decimal import Decimal
from uuid import UUID

from argon2 import PasswordHasher

from app import create_app
from app.extensions import db
from app.models import Company, CompanyMembership, Customer, Product, User


def _login(client, email, company_id):
    response = client.post("/api/auth/login", json={
        "email": email,
        "password": "a-very-strong-test-password",
    })
    assert response.status_code == 200
    selected = client.post("/api/auth/company", json={"company_id": company_id})
    assert selected.status_code == 200


def test_compliance_required_stock_is_received_to_quarantine_until_independent_verification():
    app = create_app({
        "TESTING": True,
        "SECRET_KEY": "compliance-test-secret",
        "SQLALCHEMY_DATABASE_URI": "sqlite://",
        "WTF_CSRF_ENABLED": False,
        "RATELIMIT_ENABLED": False,
    })
    try:
        with app.app_context():
            db.create_all()
            admin = User(
                email="compliance-admin@example.test",
                password_hash=PasswordHasher().hash("a-very-strong-test-password"),
                email_verified=True,
            )
            company = Company(name="Compliance Test", slug="compliance-test")
            db.session.add_all([admin, company])
            db.session.flush()
            db.session.add(CompanyMembership(
                user_id=admin.id, company_id=company.id,
                role="admin", status="active",
            ))
            customer = Customer(
                company_id=company.id, created_by_user_id=admin.id,
                name="Synthetic Buyer",
            )
            verifier = User(
                email="independent-verifier@example.test",
                password_hash=PasswordHasher().hash("a-very-strong-test-password"),
                email_verified=True,
            )
            db.session.add_all([customer, verifier])
            db.session.flush()
            db.session.add(CompanyMembership(
                user_id=verifier.id, company_id=company.id,
                role="manager", status="active",
            ))
            product = Product(
                company_id=company.id, created_by_user_id=admin.id,
                sku="REGULATED-001", name="Synthetic regulated item",
                unit_price=Decimal("25.00"), currency="TZS",
                track_inventory=True, compliance_required=True,
            )
            db.session.add(product)
            db.session.commit()
            company_id = str(company.id)
            product_id = str(product.id)
            customer_id = str(customer.id)

        admin_client = app.test_client()
        _login(admin_client, "compliance-admin@example.test", company_id)

        receipt = admin_client.post(
            f"/api/products/{product_id}/stock-movements",
            json={
                "movement_type": "received",
                "quantity": "8",
                "reason": "Synthetic receipt for compliance test",
                "batch_code": "BATCH-TEST-001",
            },
        )
        assert receipt.status_code == 201
        batch_id = receipt.json["item"]["batch_id"]

        batches = admin_client.get(
            f"/api/products/{product_id}/stock-batches"
        ).json["items"]
        assert batches[0]["compliance_status"] == "pending_verification"
        assert batches[0]["status"] == "pending_verification"
        assert batches[0]["available_quantity"] == "0.000"

        inventory = admin_client.get("/api/inventory").json["items"][0]
        assert inventory["stock_on_hand"] == "8.000"
        assert inventory["available_quantity"] == "0.000"
        assert inventory["quarantine_quantity"] == "8.000"
        assert inventory["status"] == "pending_verification"

        sale = admin_client.post("/api/sales", json={
            "customer_id": customer_id,
            "currency": "TZS",
            "items": [{"product_id": product_id, "quantity": "1"}],
        })
        assert sale.status_code == 201
        blocked = admin_client.post(
            f"/api/sales/{sale.json['item']['id']}/complete"
        )
        assert blocked.status_code == 409
        assert "quarantined" in blocked.json["error"].lower()

        self_approval = admin_client.post(
            f"/api/stock-batches/{batch_id}/compliance",
            json={
                "decision": "approve",
                "qr_code": "QR-SYNTHETIC-001",
                "authority_name": "Tanzania Bureau of Standards",
                "authority_country": "TZ",
                "certificate_reference": "TBS-SYNTHETIC-123",
                "evidence_reference": "private-evidence-ref-001",
            },
        )
        assert self_approval.status_code == 403

        verifier_client = app.test_client()
        _login(verifier_client, "independent-verifier@example.test", company_id)

        missing_qr = verifier_client.post(
            f"/api/stock-batches/{batch_id}/compliance",
            json={
                "decision": "approve",
                "authority_name": "Tanzania Bureau of Standards",
                "authority_country": "TZ",
                "certificate_reference": "TBS-SYNTHETIC-123",
                "evidence_reference": "private-evidence-ref-001",
            },
        )
        assert missing_qr.status_code == 400

        approved = verifier_client.post(
            f"/api/stock-batches/{batch_id}/compliance",
            json={
                "decision": "approve",
                "qr_code": "QR-SYNTHETIC-001",
                "authority_name": "Tanzania Bureau of Standards",
                "authority_country": "TZ",
                "standard_reference": "TZS-SYNTHETIC-001",
                "certificate_reference": "TBS-SYNTHETIC-123",
                "evidence_reference": "private-evidence-ref-001",
            },
        )
        assert approved.status_code == 200
        assert approved.json["item"]["compliance_status"] == "approved"

        completed = admin_client.post(
            f"/api/sales/{sale.json['item']['id']}/complete"
        )
        assert completed.status_code == 200

        with app.app_context():
            from app.models import StockBatch
            saved_batch = db.session.get(StockBatch, UUID(batch_id))
            assert saved_batch.compliance_status == "approved"
            assert saved_batch.received_by_user_id != saved_batch.verified_by_user_id
    finally:
        with app.app_context():
            db.session.remove()
            db.drop_all()
