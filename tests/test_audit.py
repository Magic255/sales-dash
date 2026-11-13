import os

import pytest
from argon2 import PasswordHasher
from sqlalchemy import select, text

from app import create_app
from app.extensions import db
from app.models import AuditLog, Company, CompanyMembership, User


@pytest.fixture()
def app():
    application = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "audit-test-secret",
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
            "WTF_CSRF_ENABLED": False,
            "RATELIMIT_ENABLED": False,
        }
    )
    with application.app_context():
        db.create_all()
        user = User(
            email="admin@example.test",
            password_hash=PasswordHasher().hash("a-very-strong-test-password"),
        )
        company = Company(name="Audit Test", slug="audit-test")
        db.session.add_all([user, company])
        db.session.flush()
        db.session.add(
            CompanyMembership(
                user_id=user.id, company_id=company.id, role="admin", status="active"
            )
        )
        db.session.commit()
        yield application
        db.session.remove()
        db.drop_all()


def test_authenticated_security_actions_are_audited_and_company_scoped(app):
    client = app.test_client()
    login = client.post(
        "/api/auth/login",
        json={"email": "admin@example.test", "password": "a-very-strong-test-password"},
    )
    assert login.status_code == 200

    with app.app_context():
        global_events = db.session.scalars(
            select(AuditLog).where(AuditLog.event_type == "login_succeeded")
        ).all()
        assert len(global_events) == 1
        assert global_events[0].company_id is None
        actor_id = global_events[0].actor_user_id

        other_user = User(email="other@example.test")
        db.session.add(other_user)
        db.session.flush()
        db.session.add(
            AuditLog(
                actor_user_id=other_user.id,
                company_id=None,
                event_type="login_succeeded",
            )
        )
        db.session.commit()

    company_id = client.get("/api/auth/me").json["companies"][0]["id"]
    selected = client.post("/api/auth/company", json={"company_id": company_id})
    assert selected.status_code == 200

    logs = client.get("/api/audit-logs")
    assert logs.status_code == 200
    event_types = [item["event_type"] for item in logs.json["items"]]
    assert "company_selected" in event_types
    assert "login_succeeded" in event_types
    assert len(logs.json["items"]) == 2
    own_login = next(item for item in logs.json["items"] if item["event_type"] == "login_succeeded")
    assert own_login["actor_user_id"] == str(actor_id)
    assert own_login["company_id"] is None

    changed = client.post(
        "/api/auth/password",
        json={
            "current_password": "a-very-strong-test-password",
            "new_password": "a-different-strong-password",
        },
    )
    assert changed.status_code == 200

    with app.app_context():
        event_types = db.session.scalars(
            select(AuditLog.event_type).order_by(AuditLog.occurred_at)
        ).all()
        assert "password_changed" in event_types


def test_audit_log_pagination_is_bounded_and_validated(app):
    client = app.test_client()
    client.post(
        "/api/auth/login",
        json={"email": "admin@example.test", "password": "a-very-strong-test-password"},
    )
    company_id = client.get("/api/auth/me").json["companies"][0]["id"]
    client.post("/api/auth/company", json={"company_id": company_id})

    assert client.get("/api/audit-logs?limit=0").status_code == 400
    assert client.get("/api/audit-logs?limit=not-a-number").status_code == 400
    assert client.get("/api/audit-logs?limit=101").status_code == 400


def test_postgres_runtime_role_cannot_modify_or_delete_audit_logs():
    if not os.environ.get("APP_DATABASE_URL"):
        pytest.skip("CI PostgreSQL runtime-role credentials are not configured.")

    application = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "audit-runtime-test-secret",
            "SQLALCHEMY_DATABASE_URI": os.environ["APP_DATABASE_URL"],
            "WTF_CSRF_ENABLED": False,
            "RATELIMIT_ENABLED": False,
        }
    )
    with application.app_context():
        privileges = db.session.execute(
            text(
                """
                SELECT
                    has_table_privilege(current_user, 'audit_logs', 'SELECT'),
                    has_table_privilege(current_user, 'audit_logs', 'INSERT'),
                    has_table_privilege(current_user, 'audit_logs', 'UPDATE'),
                    has_table_privilege(current_user, 'audit_logs', 'DELETE')
                """
            )
        ).one()
        assert privileges == (True, True, False, False)
