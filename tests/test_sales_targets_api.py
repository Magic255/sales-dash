from datetime import date
from decimal import Decimal

from argon2 import PasswordHasher

from app import create_app
from app.extensions import db
from app.models import (
    Company, CompanyMembership, Customer, Product, Sale, SalesTarget, User,
)


def make_client(role="admin", suffix="one"):
    application = create_app({
        "TESTING": True,
        "SECRET_KEY": "sales-target-test-secret",
        "SQLALCHEMY_DATABASE_URI": "sqlite://",
        "WTF_CSRF_ENABLED": False,
        "RATELIMIT_ENABLED": False,
    })
    with application.app_context():
        db.create_all()
        user = User(
            email=f"{role}-{suffix}@example.test",
            password_hash=PasswordHasher().hash("a-very-strong-test-password"),
            email_verified=True,
        )
        company = Company(name="Target Company", slug=f"target-{role}-{suffix}")
        db.session.add_all([user, company])
        db.session.flush()
        db.session.add(CompanyMembership(
            user_id=user.id, company_id=company.id, role=role, status="active"
        ))
        company_id = str(company.id)
        db.session.commit()
    client = application.test_client()
    assert client.post("/api/auth/login", json={
        "email": f"{role}-{suffix}@example.test",
        "password": "a-very-strong-test-password",
    }).status_code == 200
    assert client.post("/api/auth/company", json={"company_id": company_id}).status_code == 200
    return application, client


def cleanup(application):
    with application.app_context():
        db.session.remove()
        db.drop_all()


def test_admin_can_save_and_read_company_monthly_target():
    app, client = make_client()
    try:
        saved = client.put("/api/sales-targets", json={
            "month": "2026-11", "target_type": "company",
            "currency": "tzs", "target_amount": "1000000.00",
        })
        assert saved.status_code == 200
        assert saved.json["item"]["target_amount"] == "1000000.00"
        result = client.get("/api/sales-targets?month=2026-11")
        assert result.status_code == 200
        assert result.json["company_targets"] == [{
            "currency": "TZS", "target_amount": "1000000.00",
            "actual_amount": "0.00", "progress_percent": "0.00",
        }]
        updated = client.put("/api/sales-targets", json={
            "month": "2026-11", "target_type": "company",
            "currency": "TZS", "target_amount": "1500000",
        })
        assert updated.status_code == 200
        assert len(client.get("/api/sales-targets?month=2026-11").json["company_targets"]) == 1
    finally:
        cleanup(app)


def test_manager_can_set_salesperson_target_and_actual_uses_completed_sales_only():
    app, client = make_client("manager")
    try:
        with app.app_context():
            manager = db.session.query(User).filter_by(email="manager-one@example.test").one()
            company = db.session.query(Company).filter_by(slug="target-manager-one").one()
            seller = User(
                email="seller@example.test",
                password_hash=PasswordHasher().hash("a-very-strong-test-password"),
                email_verified=True,
            )
            customer = Customer(
                company_id=company.id, created_by_user_id=manager.id, name="Customer"
            )
            product = Product(
                company_id=company.id, created_by_user_id=manager.id,
                sku="TARGET-1", name="Product", unit_price=Decimal("250.00"),
                currency="TZS",
            )
            db.session.add_all([seller, customer, product])
            db.session.flush()
            db.session.add(CompanyMembership(
                user_id=seller.id, company_id=company.id,
                role="salesperson", status="active",
            ))
            db.session.flush()
            completed = Sale(
                company_id=company.id, sale_number="TARGET-COMPLETE",
                customer_id=customer.id, salesperson_user_id=seller.id,
                created_by_user_id=manager.id, status="completed",
                sale_date=date(2026, 11, 10),
                currency="TZS", total_amount=Decimal("500.00"),
            )
            draft = Sale(
                company_id=company.id, sale_number="TARGET-DRAFT",
                customer_id=customer.id, salesperson_user_id=seller.id,
                created_by_user_id=manager.id, status="draft",
                sale_date=date(2026, 11, 12),
                currency="TZS", total_amount=Decimal("900.00"),
            )
            db.session.add_all([completed, draft])
            db.session.commit()
            seller_id = str(seller.id)

        saved = client.put("/api/sales-targets", json={
            "month": "2026-11", "target_type": "salesperson",
            "salesperson_user_id": seller_id, "currency": "TZS",
            "target_amount": "1000",
        })
        assert saved.status_code == 200
        result = client.get("/api/sales-targets?month=2026-11")
        assert result.status_code == 200
        assert result.json["salesperson_targets"][0]["actual_amount"] == "500.00"
        assert result.json["salesperson_targets"][0]["progress_percent"] == "50.00"
    finally:
        cleanup(app)


def test_salesperson_can_only_view_own_target_and_cannot_manage_targets():
    app, client = make_client("salesperson")
    try:
        with app.app_context():
            seller = db.session.query(User).filter_by(email="salesperson-one@example.test").one()
            company = db.session.query(Company).filter_by(slug="target-salesperson-one").one()
            manager = User(
                email="other-seller@example.test",
                password_hash=PasswordHasher().hash("a-very-strong-test-password"),
                email_verified=True,
            )
            db.session.add(manager)
            db.session.flush()
            db.session.add(CompanyMembership(
                user_id=manager.id, company_id=company.id,
                role="salesperson", status="active",
            ))
            db.session.add_all([
                SalesTarget(
                    company_id=company.id, period_start=date(2026, 11, 1),
                    target_type="salesperson", salesperson_user_id=seller.id,
                    currency="TZS", target_amount=Decimal("100"),
                ),
                __import__("app.models", fromlist=["SalesTarget"]).SalesTarget(
                    company_id=company.id, period_start=__import__("datetime").date(2026, 11, 1),
                    target_type="salesperson", salesperson_user_id=manager.id,
                    currency="TZS", target_amount=Decimal("200"),
                ),
            ])
            db.session.commit()
        result = client.get("/api/sales-targets?month=2026-11")
        assert result.status_code == 200
        assert len(result.json["salesperson_targets"]) == 1
        assert result.json["salesperson_targets"][0]["target_amount"] == "100.00"
        assert result.json["salespeople"] == []
        assert client.put("/api/sales-targets", json={
            "month": "2026-11", "target_type": "company",
            "currency": "TZS", "target_amount": "100",
        }).status_code == 403
    finally:
        cleanup(app)


def test_invalid_month_and_target_amount_are_rejected():
    app, client = make_client()
    try:
        assert client.get("/api/sales-targets?month=2026-13").status_code == 400
        assert client.put("/api/sales-targets", json={
            "month": "2026-11", "target_type": "company",
            "currency": "TZS", "target_amount": "-5",
        }).status_code == 400
    finally:
        cleanup(app)
