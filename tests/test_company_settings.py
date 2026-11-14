from uuid import uuid4

import pytest
from argon2 import PasswordHasher

from app import create_app
from app.extensions import db
from app.models import AuditLog, Company, CompanyMembership, User


def make_company_client(role="admin"):
    application = create_app({
        "TESTING": True,
        "SECRET_KEY": "company-settings-test-secret",
        "SQLALCHEMY_DATABASE_URI": "sqlite://",
        "WTF_CSRF_ENABLED": False,
        "RATELIMIT_ENABLED": False,
    })
    with application.app_context():
        db.create_all()
        user = User(
            email=f"{role}@settings.example.test",
            password_hash=PasswordHasher().hash("a-very-strong-test-password"),
            email_verified=True,
        )
        company = Company(name="Original Company", slug=f"settings-{role}")
        db.session.add_all([user, company])
        db.session.flush()
        db.session.add(CompanyMembership(
            user_id=user.id, company_id=company.id, role=role, status="active"
        ))
        company_id = str(company.id)
        db.session.commit()

    client = application.test_client()
    assert client.post("/api/auth/login", json={
        "email": f"{role}@settings.example.test",
        "password": "a-very-strong-test-password",
    }).status_code == 200
    assert client.post("/api/auth/company", json={"company_id": company_id}).status_code == 200
    return application, client


def test_admin_can_read_and_update_company_display_name():
    application, client = make_company_client()
    try:
        current = client.get("/api/company/settings")
        assert current.status_code == 200
        assert current.json["item"]["name"] == "Original Company"
        updated = client.patch(
            "/api/company/settings", json={"name": "  New Company Name  "}
        )
        assert updated.status_code == 200
        assert updated.json["item"]["name"] == "New Company Name"
        assert updated.json["item"]["slug"] == "settings-admin"
        with application.app_context():
            events = db.session.query(AuditLog).filter_by(
                event_type="company_settings_updated"
            ).all()
            assert len(events) == 1
    finally:
        with application.app_context():
            db.session.remove()
            db.drop_all()


def test_company_settings_are_not_available_to_non_admin_roles():
    for role in ("manager", "salesperson", "viewer"):
        application, client = make_company_client(role)
        try:
            assert client.get("/api/company/settings").status_code == 403
            assert client.patch(
                "/api/company/settings", json={"name": "Not allowed"}
            ).status_code == 403
        finally:
            with application.app_context():
                db.session.remove()
                db.drop_all()


def test_company_settings_reject_invalid_payloads_without_changing_data():
    application, client = make_company_client()
    try:
        for payload in ([], {}, {"name": ""}, {"name": "  "}, {"name": "x" * 161},
                        {"name": 123}, {"name": "Changed", "slug": "attacker-choice"}):
            response = client.patch("/api/company/settings", json=payload)
            assert response.status_code == 400
        assert client.get("/api/company/settings").json["item"]["name"] == "Original Company"
    finally:
        with application.app_context():
            db.session.remove()
            db.drop_all()


def test_unchanged_company_name_does_not_create_audit_noise():
    application, client = make_company_client()
    try:
        response = client.patch("/api/company/settings", json={"name": "Original Company"})
        assert response.status_code == 200
        with application.app_context():
            assert db.session.query(AuditLog).filter_by(
                event_type="company_settings_updated"
            ).count() == 0
    finally:
        with application.app_context():
            db.session.remove()
            db.drop_all()


def test_postgres_restricted_runtime_role_can_update_company_name():
    import os

    if not os.environ.get("APP_DATABASE_URL") or not os.environ.get("DATABASE_URL"):
        pytest.skip("CI PostgreSQL runtime-role credentials are not configured.")

    company_name = "Restricted Settings Company"
    admin_app = create_app({
        "TESTING": True,
        "SECRET_KEY": "company-settings-admin-test",
        "SQLALCHEMY_DATABASE_URI": os.environ["DATABASE_URL"],
        "WTF_CSRF_ENABLED": False,
    })
    runtime_app = create_app({
        "TESTING": True,
        "SECRET_KEY": "company-settings-runtime-test",
        "SQLALCHEMY_DATABASE_URI": os.environ["APP_DATABASE_URL"],
        "WTF_CSRF_ENABLED": False,
        "RATELIMIT_ENABLED": False,
    })
    email = f"{company_name.lower().replace(' ', '-')}-{uuid4()}@example.test"
    with admin_app.app_context():
        user = User(
            email=email,
            password_hash=PasswordHasher().hash("a-very-strong-test-password"),
            email_verified=True,
        )
        company = Company(name=company_name, slug=f"settings-{uuid4().hex}")
        db.session.add_all([user, company])
        db.session.flush()
        db.session.add(CompanyMembership(
            user_id=user.id, company_id=company.id, role="admin", status="active"
        ))
        company_id, user_id = company.id, user.id
        db.session.commit()

    try:
        client = runtime_app.test_client()
        assert client.post("/api/auth/login", json={
            "email": email, "password": "a-very-strong-test-password"
        }).status_code == 200
        assert client.post("/api/auth/company", json={"company_id": str(company_id)}).status_code == 200
        updated = client.patch("/api/company/settings", json={"name": "Updated by runtime"})
        assert updated.status_code == 200
        assert updated.json["item"]["name"] == "Updated by runtime"
    finally:
        with admin_app.app_context():
            db.session.execute(db.delete(Company).where(Company.id == company_id))
            db.session.execute(db.delete(User).where(User.id == user_id))
            db.session.commit()
