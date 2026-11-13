from uuid import uuid4

import pytest
from sqlalchemy import text

from app import create_app
from app.extensions import db
from app.models import Company, CompanyMembership, User
from app.tenancy import TenantAccessDenied, set_tenant_context


@pytest.fixture
def postgres_app():
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-only-secret",
            "SQLALCHEMY_DATABASE_URI": __import__("os").environ.get("DATABASE_URL", "sqlite://"),
        }
    )
    if db.engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL row-level security tests require PostgreSQL.")
    return app


def make_identity():
    user = User(email=f"{uuid4()}@example.test")
    company_a = Company(name="Boundary Company A", slug=f"boundary-a-{uuid4().hex}")
    company_b = Company(name="Boundary Company B", slug=f"boundary-b-{uuid4().hex}")
    db.session.add_all([user, company_a, company_b])
    db.session.flush()
    db.session.add(
        CompanyMembership(
            company_id=company_a.id,
            user_id=user.id,
            role="admin",
            status="active",
        )
    )
    db.session.commit()
    return user, company_a, company_b


def test_company_rows_are_hidden_without_verified_context(postgres_app):
    with postgres_app.app_context():
        user, company_a, company_b = make_identity()
        try:
            with db.session.begin():
                db.session.execute(text("SET LOCAL ROLE sales_dash_app"))
                visible_ids = set(db.session.scalars(db.select(Company.id)).all())

            assert visible_ids == set()

            with db.session.begin():
                db.session.execute(text("SET LOCAL ROLE sales_dash_app"))
                set_tenant_context(db.session, user.id, company_a.id)
                visible_ids = set(db.session.scalars(db.select(Company.id)).all())

            assert visible_ids == {company_a.id}
            assert company_b.id not in visible_ids
        finally:
            db.session.rollback()
            db.session.delete(user)
            db.session.delete(company_a)
            db.session.delete(company_b)
            db.session.commit()


def test_user_cannot_select_a_company_without_active_membership(postgres_app):
    with postgres_app.app_context():
        user, company_a, company_b = make_identity()
        try:
            with db.session.begin():
                db.session.execute(text("SET LOCAL ROLE sales_dash_app"))
                with pytest.raises(TenantAccessDenied):
                    set_tenant_context(db.session, user.id, company_b.id)
        finally:
            db.session.rollback()
            db.session.delete(user)
            db.session.delete(company_a)
            db.session.delete(company_b)
            db.session.commit()
