import os
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
            "SQLALCHEMY_DATABASE_URI": os.environ.get("DATABASE_URL", "sqlite://"),
        }
    )
    with app.app_context():
        if db.engine.dialect.name != "postgresql":
            pytest.skip("PostgreSQL row-level security tests require PostgreSQL.")
        with db.engine.begin() as connection:
            connection.exec_driver_sql("DROP TABLE IF EXISTS tenant_boundary_probe")
            connection.exec_driver_sql(
                """
                CREATE TABLE tenant_boundary_probe (
                    id uuid PRIMARY KEY,
                    company_id uuid NOT NULL,
                    payload text NOT NULL
                )
                """
            )
            connection.exec_driver_sql(
                "ALTER TABLE tenant_boundary_probe ENABLE ROW LEVEL SECURITY"
            )
            connection.exec_driver_sql(
                "ALTER TABLE tenant_boundary_probe FORCE ROW LEVEL SECURITY"
            )
            connection.exec_driver_sql(
                """
                CREATE POLICY tenant_boundary_probe_company_isolation
                ON tenant_boundary_probe
                FOR SELECT TO sales_dash_app
                USING (
                    company_id =
                    NULLIF(current_setting('app.current_company_id', true), '')::uuid
                )
                """
            )
            connection.exec_driver_sql(
                "GRANT SELECT ON tenant_boundary_probe TO sales_dash_app"
            )
        yield app
        with db.engine.begin() as connection:
            connection.exec_driver_sql("DROP TABLE IF EXISTS tenant_boundary_probe")


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


def test_company_rows_and_tenant_records_are_isolated(postgres_app):
    with postgres_app.app_context():
        user, company_a, company_b = make_identity()
        user_id, company_a_id, company_b_id = user.id, company_a.id, company_b.id
        try:
            db.session.execute(
                text(
                    """
                    INSERT INTO tenant_boundary_probe (id, company_id, payload)
                    VALUES (:id_a, :company_a, 'Company A secret'),
                           (:id_b, :company_b, 'Company B secret')
                    """
                ),
                {
                    "id_a": str(uuid4()),
                    "id_b": str(uuid4()),
                    "company_a": str(company_a_id),
                    "company_b": str(company_b_id),
                },
            )
            db.session.commit()

            with db.session.begin():
                db.session.execute(text("SET LOCAL ROLE sales_dash_app"))
                visible_companies = set(db.session.scalars(db.select(Company.id)).all())
                visible_records = db.session.execute(
                    text("SELECT payload FROM tenant_boundary_probe")
                ).scalars().all()

            assert visible_companies == set()
            assert visible_records == []

            with db.session.begin():
                db.session.execute(text("SET LOCAL ROLE sales_dash_app"))
                set_tenant_context(db.session, user_id, company_a_id)
                visible_companies = set(db.session.scalars(db.select(Company.id)).all())
                visible_records = db.session.execute(
                    text("SELECT payload FROM tenant_boundary_probe")
                ).scalars().all()

            assert visible_companies == {company_a_id}
            assert visible_records == ["Company A secret"]
            assert company_b_id not in visible_companies
            assert "Company B secret" not in visible_records
        finally:
            db.session.rollback()
            db.session.execute(
                text("DELETE FROM companies WHERE id IN (:company_a, :company_b)"),
                {"company_a": str(company_a_id), "company_b": str(company_b_id)},
            )
            db.session.execute(
                text("DELETE FROM users WHERE id = :user_id"),
                {"user_id": str(user_id)},
            )
            db.session.commit()


def test_user_cannot_select_a_company_without_active_membership(postgres_app):
    with postgres_app.app_context():
        user, company_a, company_b = make_identity()
        user_id, company_a_id, company_b_id = user.id, company_a.id, company_b.id
        try:
            with db.session.begin():
                db.session.execute(text("SET LOCAL ROLE sales_dash_app"))
                with pytest.raises(TenantAccessDenied):
                    set_tenant_context(db.session, user_id, company_b_id)
        finally:
            db.session.rollback()
            db.session.execute(
                text("DELETE FROM companies WHERE id IN (:company_a, :company_b)"),
                {"company_a": str(company_a_id), "company_b": str(company_b_id)},
            )
            db.session.execute(
                text("DELETE FROM users WHERE id = :user_id"),
                {"user_id": str(user_id)},
            )
            db.session.commit()
