from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app import create_app
from app.extensions import db
from app.models import Company, CompanyMembership, User


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
