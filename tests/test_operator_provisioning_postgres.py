import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app import create_app
from app.models import Company, CompanyMembership, User


pytestmark = pytest.mark.skipif(
    not os.environ.get("PROVISIONER_DATABASE_URL"),
    reason="A dedicated PostgreSQL table-owner provisioning login is required.",
)


def make_postgres_provisioning_app():
    return create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "postgres-provisioning-test-only",
            "SQLALCHEMY_DATABASE_URI": os.environ["DATABASE_URL"],
            "ADMIN_DATABASE_URL": os.environ["PROVISIONER_DATABASE_URL"],
            "WTF_CSRF_ENABLED": False,
            "RATELIMIT_ENABLED": False,
        }
    )


def cleanup_rows(user_email, company_name):
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    try:
        with engine.begin() as connection:
            user_id = connection.scalar(
                text("SELECT id FROM users WHERE email = :email"),
                {"email": user_email},
            )
            company_ids = connection.execute(
                text(
                    "SELECT id FROM companies WHERE name = :company_name "
                    "UNION SELECT company_id FROM company_memberships "
                    "WHERE user_id = :user_id"
                ),
                {"company_name": company_name, "user_id": user_id},
            ).scalars().all() if user_id is not None else connection.execute(
                text("SELECT id FROM companies WHERE name = :company_name"),
                {"company_name": company_name},
            ).scalars().all()
            if user_id is not None:
                connection.execute(
                    text("DELETE FROM company_memberships WHERE user_id = :user_id"),
                    {"user_id": user_id},
                )
            for company_id in company_ids:
                connection.execute(
                    text("DELETE FROM company_memberships WHERE company_id = :company_id"),
                    {"company_id": company_id},
                )
                connection.execute(
                    text("DELETE FROM companies WHERE id = :company_id"),
                    {"company_id": company_id},
                )
            if user_id is not None:
                connection.execute(
                    text("DELETE FROM users WHERE id = :user_id"),
                    {"user_id": user_id},
                )
    finally:
        engine.dispose()


def test_create_admin_works_with_non_superuser_table_owner():
    app = make_postgres_provisioning_app()
    email = f"operator-admin-{uuid4()}@example.test"
    company_name = f"Provisioned Company {uuid4().hex[:8]}"
    try:
        result = app.test_cli_runner().invoke(
            args=["create-admin"],
            input=(
                f"{email}\n{company_name}\n"
                "a-strong-test-password\na-strong-test-password\n"
            ),
        )
        assert result.exit_code == 0, result.output
        assert "Administrator created" in result.output

        engine = create_engine(os.environ["PROVISIONER_DATABASE_URL"])
        try:
            with Session(engine) as session:
                user = session.scalar(select(User).where(User.email == email))
                company = session.scalar(
                    select(Company).where(Company.name == company_name)
                )
                assert user is not None
                assert user.email_verified is True
                assert company is not None
                membership = session.get(
                    CompanyMembership, (company.id, user.id)
                )
                assert membership is not None
                assert membership.role == "admin"
                assert membership.status == "active"
        finally:
            engine.dispose()
    finally:
        cleanup_rows(email, company_name)


def test_create_company_works_with_non_superuser_table_owner():
    app = make_postgres_provisioning_app()
    email = f"existing-admin-{uuid4()}@example.test"
    company_name = f"Additional Company {uuid4().hex[:8]}"
    admin_engine = create_engine(os.environ["DATABASE_URL"])
    try:
        with Session(admin_engine) as session, session.begin():
            user = User(
                email=email,
                display_name="Existing Verified Admin",
                password_hash="test-only-password-hash",
                email_verified=True,
            )
            session.add(user)

        result = app.test_cli_runner().invoke(
            args=["create-company"],
            input=f"{email}\n{company_name}\n",
        )
        assert result.exit_code == 0, result.output
        assert f"Company {company_name} created" in result.output

        provisioner_engine = create_engine(
            os.environ["PROVISIONER_DATABASE_URL"]
        )
        try:
            with Session(provisioner_engine) as session:
                company = session.scalar(
                    select(Company).where(Company.name == company_name)
                )
                user = session.scalar(select(User).where(User.email == email))
                assert company is not None
                assert user is not None
                membership = session.get(
                    CompanyMembership, (company.id, user.id)
                )
                assert membership is not None
                assert membership.role == "admin"
        finally:
            provisioner_engine.dispose()
    finally:
        cleanup_rows(email, company_name)
        admin_engine.dispose()
