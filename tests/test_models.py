from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError

from app import create_app
from app.extensions import db
from app.models import (\n    Company, CompanyMembership, Customer, Product, Sale, SaleItem, User,\n)


@pytest.fixture()
def app():
    application = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-only-secret",
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
        }
    )
    with application.app_context():
        @event.listens_for(db.engine, "connect")
        def enable_sqlite_foreign_keys(connection, _record):
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()


def test_user_can_belong_to_multiple_companies(app):
    with app.app_context():
        user = User(email="person@example.com")
        first = Company(name="First Company", slug="first-company")
        second = Company(name="Second Company", slug="second-company")
        db.session.add_all([user, first, second])
        db.session.flush()

        db.session.add_all(
            [
                CompanyMembership(company=first, user=user, role="admin"),
                CompanyMembership(company=second, user=user, role="viewer"),
            ]
        )
        db.session.commit()

        assert len(user.memberships) == 2
        assert {membership.role for membership in user.memberships} == {"admin", "viewer"}


def test_membership_requires_existing_user_and_company(app):
    with app.app_context():
        membership = CompanyMembership(
            company_id=uuid4(), user_id=uuid4(), role="viewer", status="active"
        )
        db.session.add(membership)

        with pytest.raises(IntegrityError):
            db.session.commit()


def test_membership_rejects_unsupported_role(app):
    with app.app_context():
        user = User(email="person@example.com")
        company = Company(name="Example Company", slug="example-company")
        db.session.add_all([user, company])
        db.session.flush()
        db.session.add(
            CompanyMembership(company=company, user=user, role="owner", status="active")
        )

        with pytest.raises(IntegrityError):
            db.session.commit()


def test_email_and_company_slug_are_unique(app):
    with app.app_context():
        db.session.add_all(
            [
                User(email="same@example.com"),
                User(email="same@example.com"),
            ]
        )
        with pytest.raises(IntegrityError):
            db.session.commit()


def test_email_and_company_slug_are_normalized(app):
    with app.app_context():
        user = User(email="  PERSON@Example.COM ")
        company = Company(name="Example Company", slug="  EXAMPLE-Co  ")
        db.session.add_all([user, company])
        db.session.commit()

        assert user.email == "person@example.com"
        assert company.slug == "example-co"


def test_company_rejects_blank_name(app):
    with app.app_context():
        db.session.add(Company(name="   ", slug="valid-slug"))
        with pytest.raises(IntegrityError):
            db.session.commit()


def test_membership_rejects_unsupported_status(app):
    with app.app_context():
        user = User(email="person@example.com")
        company = Company(name="Example Company", slug="example-company")
        db.session.add_all([user, company])
        db.session.flush()
        db.session.add(
            CompanyMembership(company=company, user=user, role="viewer", status="deleted")
        )

        with pytest.raises(IntegrityError):
            db.session.commit()


def test_company_slug_is_unique(app):
    with app.app_context():
        db.session.add_all(
            [
                Company(name="First Company", slug="shared-slug"),
                Company(name="Second Company", slug="shared-slug"),
            ]
        )
        with pytest.raises(IntegrityError):
            db.session.commit()


def test_sales_records_are_bound_to_their_company(app):
    with app.app_context():
        user = User(email="seller@example.com")
        company_a = Company(name="Company A", slug="company-a")
        company_b = Company(name="Company B", slug="company-b")
        db.session.add_all([user, company_a, company_b])
        db.session.flush()
        db.session.add_all([
            CompanyMembership(company=company_a, user=user, role="admin"),
            CompanyMembership(company=company_b, user=user, role="admin"),
        ])
        db.session.flush()

        customer_a = Customer(
            company_id=company_a.id,
            name="Customer A",
            email="customer@example.com",
            created_by_user_id=user.id,
        )
        product_a = Product(
            company_id=company_a.id,
            sku="SKU-A",
            name="Product A",
            unit_price=Decimal("125.00"),
            currency="TZS",
            created_by_user_id=user.id,
        )
        product_b = Product(
            company_id=company_b.id,
            sku="SKU-B",
            name="Product B",
            unit_price=Decimal("250.00"),
            currency="TZS",
            created_by_user_id=user.id,
        )
        db.session.add_all([customer_a, product_a, product_b])
        db.session.flush()

        sale = Sale(
            company_id=company_a.id,
            sale_number="SALE-0001",
            customer_id=customer_a.id,
            salesperson_user_id=user.id,
            created_by_user_id=user.id,
            sale_date=date(2026, 11, 13),
            currency="TZS",
            subtotal=Decimal("250.00"),
            total_amount=Decimal("250.00"),
        )
        db.session.add(sale)
        db.session.flush()

        valid_item = SaleItem(
            company_id=company_a.id,
            sale_id=sale.id,
            product_id=product_a.id,
            product_name="Product A",
            sku_snapshot="SKU-A",
            quantity=Decimal("2.000"),
            unit_price=Decimal("125.00"),
            line_total=Decimal("250.00"),
        )
        db.session.add(valid_item)
        db.session.commit()

        assert valid_item.company_id == sale.company_id

        invalid_item = SaleItem(
            company_id=company_a.id,
            sale_id=sale.id,
            product_id=product_b.id,
            product_name="Product B",
            sku_snapshot="SKU-B",
            quantity=Decimal("1.000"),
            unit_price=Decimal("250.00"),
            line_total=Decimal("250.00"),
        )
        db.session.add(invalid_item)
        with pytest.raises(IntegrityError):
            db.session.commit()
