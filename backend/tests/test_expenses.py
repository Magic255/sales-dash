from datetime import date
from decimal import Decimal
from uuid import UUID

from argon2 import PasswordHasher

from app import create_app
from app.extensions import db
from app.models import Company, CompanyMembership, Expense, User


def _app():
    app = create_app({
        "TESTING": True,
        "SECRET_KEY": "expense-ledger-test-secret",
        "SQLALCHEMY_DATABASE_URI": "sqlite://",
        "WTF_CSRF_ENABLED": False,
        "RATELIMIT_ENABLED": False,
    })
    with app.app_context():
        db.create_all()
        password = PasswordHasher().hash("a-very-strong-test-password")
        admin = User(email="expense-admin@example.test", password_hash=password, email_verified=True)
        manager = User(email="expense-manager@example.test", password_hash=password, email_verified=True)
        salesperson = User(email="expense-sales@example.test", password_hash=password, email_verified=True)
        company = Company(name="Expense Test", slug="expense-test")
        db.session.add_all([admin, manager, salesperson, company])
        db.session.flush()
        db.session.add_all([
            CompanyMembership(user_id=admin.id, company_id=company.id, role="admin", status="active"),
            CompanyMembership(user_id=manager.id, company_id=company.id, role="manager", status="active"),
            CompanyMembership(user_id=salesperson.id, company_id=company.id, role="salesperson", status="active"),
        ])
        db.session.commit()
        return app, str(company.id), str(admin.id)


def _login(client, email, company_id):
    response = client.post("/api/auth/login", json={
        "email": email, "password": "a-very-strong-test-password",
    })
    assert response.status_code == 200
    assert client.post("/api/auth/company", json={"company_id": company_id}).status_code == 200


def _payload(**overrides):
    result = {
        "description": "Monthly shop rent",
        "category": "rent",
        "amount": "450000.00",
        "currency": "tzs",
        "expense_date": date.today().isoformat(),
        "payment_method": "Bank transfer",
        "reference": "RENT-SYNTH-001",
        "notes": "Synthetic test expense",
    }
    result.update(overrides)
    return result


def test_admin_and_manager_can_record_expenses_and_admin_can_void_with_reason():
    app, company_id, _admin_id = _app()
    try:
        admin = app.test_client()
        manager = app.test_client()
        _login(admin, "expense-admin@example.test", company_id)
        _login(manager, "expense-manager@example.test", company_id)

        created = manager.post("/api/expenses", json=_payload())
        assert created.status_code == 201
        expense_id = created.json["item"]["id"]
        assert created.json["item"]["currency"] == "TZS"
        assert created.json["item"]["status"] == "recorded"

        listed = manager.get("/api/expenses")
        assert listed.status_code == 200
        assert listed.json["totals_by_currency"] == [{"currency": "TZS", "amount": "450000.00"}]

        missing_reason = admin.post(f"/api/expenses/{expense_id}/void", json={"reason": " "})
        assert missing_reason.status_code == 400
        voided = admin.post(
            f"/api/expenses/{expense_id}/void",
            json={"reason": "Duplicate synthetic receipt entered in error."},
        )
        assert voided.status_code == 200
        assert voided.json["item"]["status"] == "void"

        with app.app_context():
            stored = db.session.get(Expense, UUID(expense_id))
            assert stored.status == "void"
            assert stored.amount == Decimal("450000.00")
            assert stored.void_reason.startswith("Duplicate")
    finally:
        with app.app_context():
            db.session.remove()
            db.drop_all()


def test_salesperson_cannot_view_or_create_company_expenses():
    app, company_id, _admin_id = _app()
    try:
        client = app.test_client()
        _login(client, "expense-sales@example.test", company_id)
        assert client.get("/api/expenses").status_code == 403
        assert client.post("/api/expenses", json=_payload()).status_code == 403
    finally:
        with app.app_context():
            db.session.remove()
            db.drop_all()


def test_expense_validation_rejects_nonpositive_amount_and_invalid_currency():
    app, company_id, _admin_id = _app()
    try:
        client = app.test_client()
        _login(client, "expense-admin@example.test", company_id)
        assert client.post("/api/expenses", json=_payload(amount="0")).status_code == 400
        assert client.post("/api/expenses", json=_payload(currency="US")).status_code == 400
        assert client.post("/api/expenses", json=_payload(amount="1.001")).status_code == 400
    finally:
        with app.app_context():
            db.session.remove()
            db.drop_all()
