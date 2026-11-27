# ruff: noqa: I001
from decimal import Decimal
from io import BytesIO
from uuid import UUID

from argon2 import PasswordHasher
from cryptography.fernet import Fernet

from app import create_app
from app.extensions import db
from app.models import (
    Company,
    CompanyMembership,
    ComplianceEvidenceFile,
    Customer,
    Product,
    User,
)


TEST_EVIDENCE_KEY = Fernet.generate_key().decode("ascii")


def _verification_details(source_url="https://tbs.go.tz/certified-product-companies"):
    return {
        "authority_role": "standards_body",
        "verification_method": "official_registry",
        "verification_source_url": source_url,
        "verification_reference": "TBS-SYNTHETIC-123",
        "verified_product_identifier": "Synthetic regulated item / REGULATED-001",
        "verified_scope": "Product identity, standard and Tanzania market matched",
    }


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
        "COMPLIANCE_EVIDENCE_ENCRYPTION_KEY": TEST_EVIDENCE_KEY,
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
            salesperson = User(
                email="evidence-salesperson@example.test",
                password_hash=PasswordHasher().hash("a-very-strong-test-password"),
                email_verified=True,
            )
            db.session.add_all([customer, verifier, salesperson])
            db.session.flush()
            db.session.add_all([
                CompanyMembership(
                    user_id=verifier.id, company_id=company.id,
                    role="manager", status="active",
                ),
                CompanyMembership(
                    user_id=salesperson.id, company_id=company.id,
                    role="salesperson", status="active",
                ),
            ])
            product = Product(
                company_id=company.id, created_by_user_id=admin.id,
                sku="REGULATED-001", name="Synthetic regulated item",
                unit_price=Decimal("25.00"), currency="TZS",
                track_inventory=True, compliance_required=True,
                category_key="general", market_country="TZ",
            )
            db.session.add(product)
            db.session.commit()
            company_id = str(company.id)
            product_id = str(product.id)
            customer_id = str(customer.id)

        admin_client = app.test_client()
        _login(admin_client, "compliance-admin@example.test", company_id)
        policy = admin_client.post("/api/compliance-policies", json={
            "category_key": "general", "market_country": "TZ",
            "approval_mode": "required",
            "accepted_authorities": ["Tanzania Bureau of Standards"],
            "requirement_source_url": "https://tbs.go.tz/pages/pre-shipment-verification-of-conformity-pvoc",
            "requirement_reference": "TBS PVoC official guidance",
        })
        assert policy.status_code == 200

        receipt = admin_client.post(
            f"/api/products/{product_id}/stock-movements",
            json={
                "movement_type": "received",
                "quantity": "8",
                "reason": "Synthetic receipt for compliance test",
                "batch_code": "BATCH-TEST-001",
                "supplier_name": "Synthetic Supplier Ltd",
                "supplier_invoice_reference": "INV-SYNTH-001",
                "manufacturer_name": "Synthetic Manufacturer Ltd",
                "country_of_origin": "TZ",
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
                "evidence_reference": "forbidden-self-approval-test",
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

        invalid_upload = verifier_client.post(
            f"/api/stock-batches/{batch_id}/evidence",
            data={"file": (BytesIO(b"not a real PDF"), "fake.pdf")},
            content_type="multipart/form-data",
        )
        assert invalid_upload.status_code == 400

        uploaded = verifier_client.post(
            f"/api/stock-batches/{batch_id}/evidence",
            data={
                "file": (
                    BytesIO(b"%PDF-1.7\\nsynthetic certificate evidence\\n"),
                    "certificate.pdf",
                )
            },
            content_type="multipart/form-data",
        )
        assert uploaded.status_code == 201
        evidence_file_id = uploaded.json["item"]["id"]
        with app.app_context():
            stored = db.session.get(ComplianceEvidenceFile, UUID(evidence_file_id))
            assert stored is not None
            assert b"synthetic certificate evidence" not in stored.encrypted_content
        downloaded = verifier_client.get(
            f"/api/stock-batches/{batch_id}/evidence/{evidence_file_id}"
        )
        assert downloaded.status_code == 200
        assert downloaded.data.startswith(b"%PDF-1.7")
        assert downloaded.headers["Cache-Control"] == "no-store"
        evidence_list = verifier_client.get(
            f"/api/stock-batches/{batch_id}/evidence"
        )
        assert evidence_list.status_code == 200
        assert evidence_list.json["items"][0]["id"] == evidence_file_id

        salesperson_client = app.test_client()
        _login(salesperson_client, "evidence-salesperson@example.test", company_id)
        denied_download = salesperson_client.get(
            f"/api/stock-batches/{batch_id}/evidence/{evidence_file_id}"
        )
        assert denied_download.status_code == 403

        wrong_evidence = verifier_client.post(
            f"/api/stock-batches/{batch_id}/compliance",
            json={
                "decision": "approve",
                "qr_code": "QR-SYNTHETIC-001",
                "authority_name": "Tanzania Bureau of Standards",
                "authority_country": "TZ",
                "certificate_reference": "TBS-SYNTHETIC-123",
                **_verification_details(),
                "evidence_file_id": "00000000-0000-0000-0000-000000000000",
            },
        )
        assert wrong_evidence.status_code == 400

        invalid_source = verifier_client.post(
            f"/api/stock-batches/{batch_id}/compliance",
            json={
                "decision": "approve",
                "qr_code": "QR-SYNTHETIC-001",
                "authority_name": "Tanzania Bureau of Standards",
                "authority_country": "TZ",
                "certificate_reference": "TBS-SYNTHETIC-123",
                **_verification_details("http://tbs.go.tz/certified-product-companies"),
                "evidence_file_id": evidence_file_id,
            },
        )
        assert invalid_source.status_code == 400

        missing_accreditation_body = verifier_client.post(
            f"/api/stock-batches/{batch_id}/compliance",
            json={
                "decision": "approve",
                "qr_code": "QR-SYNTHETIC-001",
                "authority_name": "Tanzania Bureau of Standards",
                "authority_country": "TZ",
                "certificate_reference": "TBS-SYNTHETIC-123",
                **_verification_details(
                    "https://www.sadcas.org/accredited-organisations/product-certification-bodies"
                ),
                "verification_method": "accreditation_scope",
                "evidence_file_id": evidence_file_id,
            },
        )
        assert missing_accreditation_body.status_code == 400

        approved = verifier_client.post(
            f"/api/stock-batches/{batch_id}/compliance",
            json={
                "decision": "approve",
                "qr_code": "QR-SYNTHETIC-001",
                "authority_name": "Tanzania Bureau of Standards",
                "authority_country": "TZ",
                "standard_reference": "TZS-SYNTHETIC-001",
                "certificate_reference": "TBS-SYNTHETIC-123",
                **_verification_details(),
                "evidence_file_id": evidence_file_id,
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


def test_category_market_policy_enforces_quarantine_authorities_and_admin_exceptions():
    app = create_app({
        "TESTING": True,
        "SECRET_KEY": "category-policy-test-secret",
        "SQLALCHEMY_DATABASE_URI": "sqlite://",
        "WTF_CSRF_ENABLED": False,
        "RATELIMIT_ENABLED": False,
        "COMPLIANCE_EVIDENCE_ENCRYPTION_KEY": TEST_EVIDENCE_KEY,
    })
    try:
        with app.app_context():
            db.create_all()
            admin = User(
                email="policy-admin@example.test",
                password_hash=PasswordHasher().hash("a-very-strong-test-password"),
                email_verified=True,
            )
            manager = User(
                email="policy-manager@example.test",
                password_hash=PasswordHasher().hash("a-very-strong-test-password"),
                email_verified=True,
            )
            company = Company(name="Policy Test", slug="policy-test")
            db.session.add_all([admin, manager, company])
            db.session.flush()
            db.session.add_all([
                CompanyMembership(
                    user_id=admin.id, company_id=company.id,
                    role="admin", status="active",
                ),
                CompanyMembership(
                    user_id=manager.id, company_id=company.id,
                    role="manager", status="active",
                ),
            ])
            product = Product(
                company_id=company.id, created_by_user_id=admin.id,
                sku="FOOD-001", name="Synthetic food product",
                unit_price=Decimal("12.00"), currency="TZS",
                track_inventory=True, category_key="food", market_country="TZ",
            )
            exception_product = Product(
                company_id=company.id, created_by_user_id=admin.id,
                sku="TOOLS-001", name="Synthetic tools product",
                unit_price=Decimal("15.00"), currency="TZS",
                track_inventory=True, category_key="tools", market_country="TZ",
            )
            unconfigured_product = Product(
                company_id=company.id, created_by_user_id=admin.id,
                sku="UNCATEGORIZED-001", name="Synthetic unconfigured product",
                unit_price=Decimal("8.00"), currency="TZS",
                track_inventory=True, category_key="unconfigured", market_country="TZ",
            )
            db.session.add_all([product, exception_product, unconfigured_product])
            db.session.commit()
            company_id = str(company.id)
            product_id = str(product.id)
            exception_product_id = str(exception_product.id)
            unconfigured_product_id = str(unconfigured_product.id)

        admin_client = app.test_client()
        manager_client = app.test_client()
        _login(admin_client, "policy-admin@example.test", company_id)
        _login(manager_client, "policy-manager@example.test", company_id)

        unconfigured_receipt = manager_client.post(
            f"/api/products/{unconfigured_product_id}/stock-movements",
            json={
                "movement_type": "received", "quantity": "1",
                "reason": "Synthetic receipt without a configured policy",
                "batch_code": "FOOD-UNCONFIGURED",
                "supplier_name": "Synthetic Food Supplier",
                "supplier_invoice_reference": "INV-UNCONFIGURED",
                "manufacturer_name": "Synthetic Food Manufacturer",
                "country_of_origin": "TZ",
            },
        )
        assert unconfigured_receipt.status_code == 201
        unconfigured_batch_id = unconfigured_receipt.json["item"]["batch_id"]
        unconfigured_state = manager_client.get(
            f"/api/products/{unconfigured_product_id}/stock-batches"
        ).json["items"][0]
        assert unconfigured_state["compliance_status"] == "pending_verification"
        assert unconfigured_state["available_quantity"] == "0.000"
        no_policy_release = admin_client.post(
            f"/api/stock-batches/{unconfigured_batch_id}/compliance",
            json={
                "decision": "release_not_required",
                "notes": "No category policy exists.",
                "evidence_file_id": "00000000-0000-0000-0000-000000000000",
            },
        )
        assert no_policy_release.status_code == 409

        required = admin_client.post("/api/compliance-policies", json={
            "category_key": "food",
            "market_country": "tz",
            "approval_mode": "required",
            "accepted_authorities": ["Tanzania Bureau of Standards"],
            "requirement_source_url": "https://tbs.go.tz/pages/pre-shipment-verification-of-conformity-pvoc",
            "requirement_reference": "TBS PVoC official guidance",
        })
        assert required.status_code == 200
        assert required.json["item"]["approval_mode"] == "required"
        product_data = admin_client.get("/api/products?include_inactive=true").json["items"]
        regulated = next(item for item in product_data if item["id"] == product_id)
        assert regulated["compliance_required"] is True
        missing_market = admin_client.patch(
            f"/api/products/{product_id}", json={"market_country": None}
        )
        assert missing_market.status_code == 400

        missing_supplier_document = manager_client.post(
            f"/api/products/{product_id}/stock-movements",
            json={
                "movement_type": "received", "quantity": "1",
                "reason": "Synthetic receipt missing supplier proof",
                "batch_code": "FOOD-NO-INVOICE",
                "supplier_name": "Synthetic Food Supplier",
                "manufacturer_name": "Synthetic Food Manufacturer",
                "country_of_origin": "TZ",
            },
        )
        assert missing_supplier_document.status_code == 400
        assert "invoice or delivery note" in missing_supplier_document.json["error"]

        receipt = manager_client.post(
            f"/api/products/{product_id}/stock-movements",
            json={
                "movement_type": "received", "quantity": "5",
                "reason": "Synthetic category policy receipt",
                "batch_code": "FOOD-LOT-001",
                "supplier_name": "Synthetic Food Supplier",
                "supplier_invoice_reference": "INV-FOOD-001",
                "manufacturer_name": "Synthetic Food Manufacturer",
                "country_of_origin": "TZ",
            },
        )
        assert receipt.status_code == 201
        batch_id = receipt.json["item"]["batch_id"]
        batches = manager_client.get(
            f"/api/products/{product_id}/stock-batches"
        ).json["items"]
        assert batches[0]["compliance_status"] == "pending_verification"

        uploaded = admin_client.post(
            f"/api/stock-batches/{batch_id}/evidence",
            data={
                "file": (
                    BytesIO(b"%PDF-1.7\\nsynthetic policy evidence\\n"),
                    "policy-certificate.pdf",
                )
            },
            content_type="multipart/form-data",
        )
        assert uploaded.status_code == 201

        unknown_authority = admin_client.post(
            f"/api/stock-batches/{batch_id}/compliance",
            json={
                "decision": "approve", "qr_code": "SYNTHETIC-QR-FOOD",
                "authority_name": "Unlisted Authority", "authority_country": "TZ",
                "certificate_reference": "SYNTHETIC-CERT-1",
                **_verification_details(),
                "evidence_file_id": uploaded.json["item"]["id"],
            },
        )
        assert unknown_authority.status_code == 400

        verified = admin_client.post(
            f"/api/stock-batches/{batch_id}/compliance",
            json={
                "decision": "approve", "qr_code": "SYNTHETIC-QR-FOOD",
                "authority_name": "Tanzania Bureau of Standards", "authority_country": "TZ",
                "certificate_reference": "SYNTHETIC-CERT-1",
                **_verification_details(
                    "https://www.sadcas.org/accredited-organisations/product-certification-bodies"
                ),
                "verification_method": "accreditation_scope",
                "accreditation_body_name": "SADCAS",
                "evidence_file_id": uploaded.json["item"]["id"],
            },
        )
        assert verified.status_code == 200
        assert verified.json["item"]["compliance_status"] == "approved"

        exception_policy = admin_client.post("/api/compliance-policies", json={
            "category_key": "tools", "market_country": "TZ",
            "approval_mode": "admin_exception", "accepted_authorities": [],
            "requirement_source_url": "https://example.test/internal-tools-policy",
            "requirement_reference": "Synthetic internal policy v1",
        })
        assert exception_policy.status_code == 200
        exception_receipt = manager_client.post(
            f"/api/products/{exception_product_id}/stock-movements",
            json={
                "movement_type": "received", "quantity": "2",
                "reason": "Synthetic Admin exception receipt",
                "batch_code": "TOOLS-LOT-001",
                "supplier_name": "Synthetic Tool Supplier",
                "delivery_note_reference": "DN-TOOLS-001",
                "manufacturer_name": "Synthetic Tool Manufacturer",
                "country_of_origin": "CN",
            },
        )
        assert exception_receipt.status_code == 201
        exception_batch_id = exception_receipt.json["item"]["batch_id"]
        manager_exception = manager_client.post(
            f"/api/stock-batches/{exception_batch_id}/compliance",
            json={"decision": "exception", "notes": "Manager must not override."},
        )
        assert manager_exception.status_code == 403
        admin_exception = admin_client.post(
            f"/api/stock-batches/{exception_batch_id}/compliance",
            json={"decision": "exception", "notes": "Synthetic documented exception."},
        )
        assert admin_exception.status_code == 200
        assert admin_exception.json["item"]["compliance_status"] == "exception_approved"

        legal_policy = admin_client.post("/api/compliance-policies", json={
            "category_key": "medical-device", "market_country": "TZ",
            "approval_mode": "required",
            "accepted_authorities": ["Tanzania Medicines and Medical Devices Authority"],
            "legal_requirement": True,
            "requirement_source_url": "https://www.tmda.go.tz/pages/procedures-for-market-authorization",
            "requirement_reference": "Tanzania Medicines and Medical Devices Act, Cap. 219",
        })
        assert legal_policy.status_code == 200
        forbidden_override = admin_client.post("/api/compliance-policies", json={
            "category_key": "medical-device", "market_country": "TZ",
            "approval_mode": "admin_exception", "accepted_authorities": [],
            "legal_requirement": True,
            "requirement_source_url": "https://www.tmda.go.tz/pages/procedures-for-market-authorization",
            "requirement_reference": "Tanzania Medicines and Medical Devices Act, Cap. 219",
        })
        assert forbidden_override.status_code == 400
        legal_downgrade = admin_client.post("/api/compliance-policies", json={
            "category_key": "medical-device", "market_country": "TZ",
            "approval_mode": "not_required", "accepted_authorities": [],
            "legal_requirement": False,
            "requirement_source_url": "https://www.tmda.go.tz/pages/procedures-for-market-authorization",
            "requirement_reference": "Attempted legal policy downgrade",
        })
        assert legal_downgrade.status_code == 400
        assert "cannot be removed" in legal_downgrade.json["error"]

        not_required = admin_client.post("/api/compliance-policies", json={
            "category_key": "stationery", "market_country": "TZ",
            "approval_mode": "not_required", "accepted_authorities": [],
            "requirement_source_url": "https://example.test/stationery-policy",
            "requirement_reference": "Synthetic category assessment v1",
        })
        assert not_required.status_code == 200
        unregulated = admin_client.post("/api/products", json={
            "sku": "STATIONERY-001",
            "name": "Synthetic stationery item",
            "unit_price": "4.00",
            "cost_price": "1.00",
            "minimum_selling_price": "1.00",
            "currency": "TZS",
            "track_inventory": True,
            "category_key": "stationery",
            "market_country": "TZ",
            "compliance_required": False,
        })
        assert unregulated.status_code == 201
        assert unregulated.json["item"]["compliance_required"] is False
        unregulated_id = unregulated.json["item"]["id"]
        receipt = manager_client.post(
            f"/api/products/{unregulated_id}/stock-movements",
            json={
                "movement_type": "received", "quantity": "4",
                "reason": "Synthetic non-regulated goods receipt",
                "batch_code": "STATIONERY-LOT-001",
                "supplier_name": "Synthetic Stationery Supplier",
                "supplier_invoice_reference": "INV-STATIONERY-001",
                "manufacturer_name": "Synthetic Stationery Maker",
                "country_of_origin": "TZ",
            },
        )
        assert receipt.status_code == 201
        unregulated_batch_id = receipt.json["item"]["batch_id"]
        assert receipt.json["item"]["movement_type"] == "received"
        batch_state = admin_client.get(
            f"/api/products/{unregulated_id}/stock-batches"
        ).json["items"][0]
        assert batch_state["compliance_status"] == "pending_verification"
        assert batch_state["available_quantity"] == "0.000"
        invoice = admin_client.post(
            f"/api/stock-batches/{unregulated_batch_id}/evidence",
            data={
                "file": (
                    BytesIO(b"%PDF-1.7\\nsynthetic supplier invoice\\n"),
                    "stationery-invoice.pdf",
                )
            },
            content_type="multipart/form-data",
        )
        assert invoice.status_code == 201
        released = admin_client.post(
            f"/api/stock-batches/{unregulated_batch_id}/compliance",
            json={
                "decision": "release_not_required",
                "notes": "Synthetic category review: no product approval requirement.",
                "evidence_file_id": invoice.json["item"]["id"],
            },
        )
        assert released.status_code == 200
        assert released.json["item"]["compliance_status"] == "verified_not_required"
    finally:
        with app.app_context():
            db.session.remove()
            db.drop_all()
