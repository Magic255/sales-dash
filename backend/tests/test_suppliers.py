from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from argon2 import PasswordHasher

from app import create_app
from app.extensions import db
from app.models import Company, CompanyMembership, Product, Supplier, SupplierDocument, User


def _seed_app():
    app = create_app({
        "TESTING": True,
        "SECRET_KEY": "supplier-test-secret",
        "SQLALCHEMY_DATABASE_URI": "sqlite://",
        "WTF_CSRF_ENABLED": False,
        "RATELIMIT_ENABLED": False,
    })
    with app.app_context():
        db.create_all()
        password = PasswordHasher().hash("a-very-strong-test-password")
        admin = User(email="supplier-admin@example.test", password_hash=password, email_verified=True)
        manager = User(email="supplier-manager@example.test", password_hash=password, email_verified=True)
        company = Company(name="Supplier Test", slug="supplier-test")
        db.session.add_all([admin, manager, company])
        db.session.flush()
        db.session.add_all([
            CompanyMembership(user_id=admin.id, company_id=company.id, role="admin", status="active"),
            CompanyMembership(user_id=manager.id, company_id=company.id, role="manager", status="active"),
        ])
        db.session.commit()
        ids = (str(company.id), str(admin.id), str(manager.id))
    return app, ids


def _login(client, email, company_id):
    response = client.post("/api/auth/login", json={
        "email": email, "password": "a-very-strong-test-password",
    })
    assert response.status_code == 200
    response = client.post("/api/auth/company", json={"company_id": company_id})
    assert response.status_code == 200


def _supplier_payload():
    return {
        "legal_name": "Synthetic Supplier Limited",
        "registration_number": "REG-SYNTH-001",
        "tax_identifier": "TAX-SYNTH-001",
        "country": "tz",
        "authorised_categories": ["food"],
        "authorised_brands": ["Synthetic Brand"],
        "authorised_territories": ["tz", "ke"],
        "licence_number": "LIC-SYNTH-001",
        "licence_issuer": "Synthetic Licensing Authority",
        "licence_valid_until": (date.today() + timedelta(days=180)).isoformat(),
        "licence_source_url": "https://authority.example.test/licences/LIC-SYNTH-001",
    }


def test_supplier_submitter_cannot_self_approve_but_second_reviewer_can():
    app, (company_id, _admin_id, _manager_id) = _seed_app()
    try:
        submitter = app.test_client()
        reviewer = app.test_client()
        _login(submitter, "supplier-admin@example.test", company_id)
        _login(reviewer, "supplier-manager@example.test", company_id)

        created = submitter.post("/api/suppliers", json=_supplier_payload())
        assert created.status_code == 201
        supplier_id = created.json["item"]["id"]
        assert created.json["item"]["status"] == "pending_review"
        with app.app_context():
            db.session.add(SupplierDocument(
                company_id=UUID(company_id),
                supplier_id=UUID(supplier_id),
                uploaded_by_user_id=UUID(_admin_id),
                original_filename="synthetic-licence.pdf",
                content_type="application/pdf",
                size_bytes=12,
                sha256="a" * 64,
                encrypted_content=b"synthetic-test-ciphertext",
                scan_status="clean",
                scanned_at=datetime.now(timezone.utc),
            ))
            db.session.commit()

        self_review = submitter.post(
            f"/api/suppliers/{supplier_id}/review",
            json={"decision": "approve"},
        )
        assert self_review.status_code == 403

        approved = reviewer.post(
            f"/api/suppliers/{supplier_id}/review",
            json={"decision": "approve", "notes": "Synthetic licence details reviewed."},
        )
        assert approved.status_code == 200
        assert approved.json["item"]["status"] == "approved"

        changed = submitter.patch(
            f"/api/suppliers/{supplier_id}",
            json={"authorised_categories": ["food", "medical_devices"]},
        )
        assert changed.status_code == 200
        assert changed.json["item"]["status"] == "pending_review"
        assert changed.json["item"]["reviewed_by_user_id"] is None
    finally:
        with app.app_context():
            db.session.remove()
            db.drop_all()


def test_supplier_approval_rejects_expired_or_incomplete_licence():
    app, (company_id, _admin_id, _manager_id) = _seed_app()
    try:
        submitter = app.test_client()
        reviewer = app.test_client()
        _login(submitter, "supplier-admin@example.test", company_id)
        _login(reviewer, "supplier-manager@example.test", company_id)

        payload = _supplier_payload()
        payload["licence_valid_until"] = (date.today() - timedelta(days=1)).isoformat()
        created = submitter.post("/api/suppliers", json=payload)
        assert created.status_code == 201
        supplier_id = created.json["item"]["id"]
        response = reviewer.post(
            f"/api/suppliers/{supplier_id}/review",
            json={"decision": "approve"},
        )
        assert response.status_code == 400
        assert response.json["error"] == "A current, unexpired supplier licence is required."
    finally:
        with app.app_context():
            db.session.remove()
            db.drop_all()


def test_supplier_record_is_company_scoped():
    app, (company_id, _admin_id, _manager_id) = _seed_app()
    try:
        client = app.test_client()
        _login(client, "supplier-admin@example.test", company_id)
        created = client.post("/api/suppliers", json=_supplier_payload())
        assert created.status_code == 201
        with app.app_context():
            supplier = db.session.query(Supplier).one()
            assert supplier.company_id
            assert supplier.status == "pending_review"
    finally:
        with app.app_context():
            db.session.remove()
            db.drop_all()


def test_supplier_identity_edit_does_not_lift_suspension():
    app, (company_id, _admin_id, _manager_id) = _seed_app()
    try:
        submitter = app.test_client()
        reviewer = app.test_client()
        _login(submitter, "supplier-admin@example.test", company_id)
        _login(reviewer, "supplier-manager@example.test", company_id)

        created = submitter.post("/api/suppliers", json=_supplier_payload())
        assert created.status_code == 201
        supplier_id = created.json["item"]["id"]
        suspended = reviewer.post(
            f"/api/suppliers/{supplier_id}/review",
            json={"decision": "suspend", "notes": "Synthetic regulator notice."},
        )
        assert suspended.status_code == 200
        assert suspended.json["item"]["status"] == "suspended"

        changed = submitter.patch(
            f"/api/suppliers/{supplier_id}",
            json={"address": "Updated synthetic address"},
        )
        assert changed.status_code == 200
        assert changed.json["item"]["status"] == "suspended"
    finally:
        with app.app_context():
            db.session.remove()
            db.drop_all()


def test_stock_receipt_requires_company_approved_supplier():
    app, (company_id, _admin_id, _manager_id) = _seed_app()
    try:
        client = app.test_client()
        _login(client, "supplier-admin@example.test", company_id)
        with app.app_context():
            product = Product(
                company_id=UUID(company_id),
                created_by_user_id=UUID(_admin_id),
                sku="SYNTHETIC-RECEIPT-001",
                name="Synthetic test product",
                unit_price="25.00",
                currency="TZS",
                track_inventory=True,
                category_key="food",
            )
            db.session.add(product)
            db.session.commit()
            product_id = str(product.id)

        response = client.post(
            f"/api/products/{product_id}/stock-movements",
            json={
                "movement_type": "received",
                "quantity": "2.000",
                "reason": "Synthetic intake test",
                "batch_code": "BATCH-SYNTHETIC-001",
                "supplier_invoice_reference": "INV-SYNTHETIC-001",
                "manufacturer_name": "Synthetic Manufacturer",
                "country_of_origin": "TZ",
            },
        )
        assert response.status_code == 400
        assert response.json["error"] == "Supplier id is required."
    finally:
        with app.app_context():
            db.session.remove()
            db.drop_all()


def test_supplier_approval_requires_clean_scanned_document():
    app, (company_id, _admin_id, _manager_id) = _seed_app()
    try:
        submitter = app.test_client()
        reviewer = app.test_client()
        _login(submitter, "supplier-admin@example.test", company_id)
        _login(reviewer, "supplier-manager@example.test", company_id)
        created = submitter.post("/api/suppliers", json=_supplier_payload())
        supplier_id = created.json["item"]["id"]
        response = reviewer.post(
            f"/api/suppliers/{supplier_id}/review",
            json={"decision": "approve", "notes": "Synthetic review."},
        )
        assert response.status_code == 400
        assert "malware-scanned" in response.json["error"]
    finally:
        with app.app_context():
            db.session.remove()
            db.drop_all()
