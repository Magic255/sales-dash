from argon2 import PasswordHasher

import pytest

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
            "WTF_CSRF_ENABLED": False,
            "RATELIMIT_ENABLED": False,
        }
    )
    with application.app_context():
        db.create_all()
        user = User(
            email="admin@example.test",
            display_name="Test Admin",
            password_hash=PasswordHasher().hash("a-very-strong-test-password"),
        )
        allowed = Company(name="Allowed Company", slug="allowed-company")
        denied = Company(name="Other Company", slug="other-company")
        db.session.add_all([user, allowed, denied])
        db.session.flush()
        db.session.add(
            CompanyMembership(
                user_id=user.id, company_id=allowed.id, role="admin", status="active"
            )
        )
        db.session.commit()
        yield application
        db.session.remove()
        db.drop_all()


def test_login_and_company_selection(app):
    client = app.test_client()
    response = client.post(
        "/api/auth/login",
        json={"email": " ADMIN@example.test ", "password": "a-very-strong-test-password"},
    )
    assert response.status_code == 200
    assert response.json["authenticated"] is True

    session_cookie = response.headers.get("Set-Cookie", "")
    assert "HttpOnly" in session_cookie
    assert "SameSite=Lax" in session_cookie

    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json["authenticated"] is True
    assert len(me.json["companies"]) == 1
    allowed_id = me.json["companies"][0]["id"]

    selected = client.post("/api/auth/company", json={"company_id": allowed_id})
    assert selected.status_code == 200
    assert selected.json["selected_company"]["role"] == "admin"

    denied = client.post(
        "/api/auth/company",
        json={"company_id": str(db.session.query(Company).filter_by(slug="other-company").one().id)},
    )
    assert denied.status_code == 403


def test_login_uses_generic_error_for_unknown_email_and_wrong_password(app):
    client = app.test_client()
    unknown = client.post(
        "/api/auth/login",
        json={"email": "missing@example.test", "password": "wrong-password"},
    )
    wrong = client.post(
        "/api/auth/login",
        json={"email": "admin@example.test", "password": "wrong-password"},
    )
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json["error"] == wrong.json["error"]


def test_company_selection_requires_login(app):
    client = app.test_client()
    response = client.post("/api/auth/company", json={"company_id": "not-a-company"})
    assert response.status_code == 401


def test_logout_clears_authenticated_session(app):
    client = app.test_client()
    client.post(
        "/api/auth/login",
        json={"email": "admin@example.test", "password": "a-very-strong-test-password"},
    )
    logout = client.post("/api/auth/logout")
    assert logout.status_code == 200
    assert client.get("/api/auth/me").json["authenticated"] is False
