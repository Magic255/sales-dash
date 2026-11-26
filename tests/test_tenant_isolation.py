import os
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app import create_app
from app.extensions import db
from app.models import (
    Company,
    CompanyMembership,
    Customer,
    Product,
    ProductBatch,
    StockMovement,
    User,
)
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
                    VALUES (CAST(:id_a AS uuid), CAST(:company_a AS uuid), 'Company A secret'),
                           (CAST(:id_b AS uuid), CAST(:company_b AS uuid), 'Company B secret')
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
                text(
                    "DELETE FROM companies WHERE id IN "
                    "(CAST(:company_a AS uuid), CAST(:company_b AS uuid))"
                ),
                {"company_a": str(company_a_id), "company_b": str(company_b_id)},
            )
            db.session.execute(
                text("DELETE FROM users WHERE id = CAST(:user_id AS uuid)"),
                {"user_id": str(user_id)},
            )
            db.session.commit()


def test_user_cannot_select_a_company_without_active_membership(postgres_app):
    with postgres_app.app_context():
        user, company_a, company_b = make_identity()
        user_id, company_a_id, company_b_id = user.id, company_a.id, company_b.id
        db.session.commit()
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


def test_sales_domain_rls_filters_and_rejects_cross_company_writes(postgres_app):
    with postgres_app.app_context():
        user_a, company_a, company_b = make_identity()
        user_b = User(email=f"{uuid4()}@example.test")
        db.session.add(user_b)
        db.session.flush()
        db.session.add(
            CompanyMembership(
                company_id=company_b.id,
                user_id=user_b.id,
                role="admin",
                status="active",
            )
        )
        db.session.flush()

        customer_a = Customer(
            company_id=company_a.id,
            name="Visible Customer",
            created_by_user_id=user_a.id,
        )
        customer_b = Customer(
            company_id=company_b.id,
            name="Hidden Customer",
            created_by_user_id=user_b.id,
        )
        db.session.add_all([customer_a, customer_b])
        user_a_id = user_a.id
        user_b_id = user_b.id
        company_a_id = company_a.id
        company_b_id = company_b.id
        db.session.commit()

        try:
            db.session.execute(text("SET LOCAL ROLE sales_dash_app"))
            set_tenant_context(db.session, user_a_id, company_a_id)
            visible = db.session.scalars(
                db.select(Customer.name).order_by(Customer.name)
            ).all()
            assert visible == ["Visible Customer"]
            db.session.commit()

            db.session.execute(text("SET LOCAL ROLE sales_dash_app"))
            set_tenant_context(db.session, user_a_id, company_a_id)
            db.session.add(
                Customer(
                    company_id=company_b_id,
                    name="Attempted Cross-Company Insert",
                    created_by_user_id=user_b_id,
                )
            )
            with pytest.raises(DBAPIError):
                db.session.flush()
            db.session.rollback()
        finally:
            db.session.rollback()
            db.session.execute(
                text(
                    "DELETE FROM customers WHERE company_id IN "
                    "(CAST(:company_a AS uuid), CAST(:company_b AS uuid))"
                ),
                {"company_a": str(company_a_id), "company_b": str(company_b_id)},
            )
            db.session.execute(
                text(
                    "DELETE FROM companies WHERE id IN "
                    "(CAST(:company_a AS uuid), CAST(:company_b AS uuid))"
                ),
                {"company_a": str(company_a_id), "company_b": str(company_b_id)},
            )
            db.session.execute(
                text(
                    "DELETE FROM users WHERE id IN "
                    "(CAST(:user_a AS uuid), CAST(:user_b AS uuid))"
                ),
                {"user_a": str(user_a_id), "user_b": str(user_b_id)},
            )
            db.session.commit()


def test_inventory_batches_and_movements_are_company_isolated(postgres_app):
    with postgres_app.app_context():
        user_a, company_a, company_b = make_identity()
        user_b = User(email=f"{uuid4()}@example.test")
        db.session.add(user_b)
        db.session.flush()
        db.session.add(
            CompanyMembership(
                company_id=company_b.id,
                user_id=user_b.id,
                role="admin",
                status="active",
            )
        )
        db.session.flush()
        product_a = Product(
            company_id=company_a.id,
            created_by_user_id=user_a.id,
            sku="TENANT-INV-A",
            name="Tenant Inventory A",
            unit_price=Decimal("10.00"),
            cost_price=Decimal("5.00"),
            minimum_selling_price=Decimal("6.00"),
            currency="TZS",
            track_inventory=True,
        )
        product_b = Product(
            company_id=company_b.id,
            created_by_user_id=user_b.id,
            sku="TENANT-INV-B",
            name="Tenant Inventory B",
            unit_price=Decimal("10.00"),
            cost_price=Decimal("5.00"),
            minimum_selling_price=Decimal("6.00"),
            currency="TZS",
            track_inventory=True,
        )
        db.session.add_all([product_a, product_b])
        db.session.flush()
        batch_a = ProductBatch(
            company_id=company_a.id,
            product_id=product_a.id,
            batch_code="TENANT-BATCH-A",
            created_by_user_id=user_a.id,
        )
        batch_b = ProductBatch(
            company_id=company_b.id,
            product_id=product_b.id,
            batch_code="TENANT-BATCH-B",
            created_by_user_id=user_b.id,
        )
        db.session.add_all([batch_a, batch_b])
        db.session.flush()
        movement_a = StockMovement(
            company_id=company_a.id,
            product_id=product_a.id,
            batch_id=batch_a.id,
            actor_user_id=user_a.id,
            actor_label=user_a.email,
            movement_type="received",
            quantity_delta=Decimal("4.000"),
            reserved_delta=Decimal("0.000"),
            reason="Company A opening stock.",
        )
        movement_b = StockMovement(
            company_id=company_b.id,
            product_id=product_b.id,
            batch_id=batch_b.id,
            actor_user_id=user_b.id,
            actor_label=user_b.email,
            movement_type="received",
            quantity_delta=Decimal("9.000"),
            reserved_delta=Decimal("0.000"),
            reason="Company B opening stock.",
        )
        db.session.add_all([movement_a, movement_b])
        user_a_id, user_b_id = user_a.id, user_b.id
        company_a_id, company_b_id = company_a.id, company_b.id
        product_b_id, batch_b_id = product_b.id, batch_b.id
        db.session.commit()

        try:
            with db.session.begin():
                db.session.execute(text("SET LOCAL ROLE sales_dash_app"))
                assert db.session.scalars(db.select(ProductBatch.id)).all() == []
                assert db.session.scalars(db.select(StockMovement.id)).all() == []

            with db.session.begin():
                db.session.execute(text("SET LOCAL ROLE sales_dash_app"))
                set_tenant_context(db.session, user_a_id, company_a_id)
                app_batch = ProductBatch(
                    company_id=company_a_id,
                    product_id=product_a.id,
                    batch_code="TENANT-BATCH-A-APP",
                    created_by_user_id=user_a_id,
                )
                db.session.add(app_batch)
                db.session.flush()
                db.session.add(StockMovement(
                    company_id=company_a_id,
                    product_id=product_a.id,
                    batch_id=app_batch.id,
                    actor_user_id=user_a_id,
                    actor_label="Company A app actor",
                    movement_type="received",
                    quantity_delta=Decimal("2.000"),
                    reserved_delta=Decimal("0.000"),
                    reason="Company A app-role stock receipt.",
                ))
                db.session.flush()

            with db.session.begin():
                db.session.execute(text("SET LOCAL ROLE sales_dash_app"))
                set_tenant_context(db.session, user_a_id, company_a_id)
                visible_batches = db.session.scalars(
                    db.select(ProductBatch.batch_code).order_by(ProductBatch.batch_code)
                ).all()
                visible_movements = db.session.scalars(
                    db.select(StockMovement.reason).order_by(StockMovement.reason)
                ).all()
                assert visible_batches == ["TENANT-BATCH-A", "TENANT-BATCH-A-APP"]
                assert visible_movements == [
                    "Company A app-role stock receipt.",
                    "Company A opening stock.",
                ]

            db.session.execute(text("SET LOCAL ROLE sales_dash_app"))
            set_tenant_context(db.session, user_a_id, company_a_id)
            db.session.add(StockMovement(
                company_id=company_b_id,
                product_id=product_b_id,
                batch_id=batch_b_id,
                actor_user_id=user_b_id,
                actor_label="Company B actor",
                movement_type="received",
                quantity_delta=Decimal("1.000"),
                reserved_delta=Decimal("0.000"),
                reason="Cross-company insert attempt.",
            ))
            with pytest.raises(DBAPIError):
                db.session.flush()
            db.session.rollback()
        finally:
            db.session.rollback()
            db.session.execute(
                text("DELETE FROM stock_movements WHERE company_id IN "
                     "(CAST(:company_a AS uuid), CAST(:company_b AS uuid))"),
                {"company_a": str(company_a_id), "company_b": str(company_b_id)},
            )
            db.session.execute(
                text("DELETE FROM product_batches WHERE company_id IN "
                     "(CAST(:company_a AS uuid), CAST(:company_b AS uuid))"),
                {"company_a": str(company_a_id), "company_b": str(company_b_id)},
            )
            db.session.execute(
                text("DELETE FROM products WHERE company_id IN "
                     "(CAST(:company_a AS uuid), CAST(:company_b AS uuid))"),
                {"company_a": str(company_a_id), "company_b": str(company_b_id)},
            )
            db.session.execute(
                text("DELETE FROM companies WHERE id IN "
                     "(CAST(:company_a AS uuid), CAST(:company_b AS uuid))"),
                {"company_a": str(company_a_id), "company_b": str(company_b_id)},
            )
            db.session.execute(
                text("DELETE FROM users WHERE id IN "
                     "(CAST(:user_a AS uuid), CAST(:user_b AS uuid))"),
                {"user_a": str(user_a_id), "user_b": str(user_b_id)},
            )
            db.session.commit()
