import pytest
from argon2 import PasswordHasher

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
            email_verified=True,
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

    with app.app_context():
        denied_company_id = str(
            db.session.query(Company).filter_by(slug="other-company").one().id
        )
    denied = client.post(
        "/api/auth/company",
        json={"company_id": denied_company_id},
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



def test_postgres_login_and_company_selection_use_restricted_role():
    import os
    from uuid import uuid4

    from argon2 import PasswordHasher

    if not os.environ.get("APP_DATABASE_URL") or not os.environ.get("DATABASE_URL"):
        pytest.skip("CI PostgreSQL runtime-role credentials are not configured.")

    email = f"{uuid4()}@example.test"
    admin_app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "admin-test-secret",
            "SQLALCHEMY_DATABASE_URI": os.environ["DATABASE_URL"],
            "WTF_CSRF_ENABLED": False,
        }
    )
    runtime_app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "runtime-test-secret",
            "SQLALCHEMY_DATABASE_URI": os.environ["APP_DATABASE_URL"],
            "WTF_CSRF_ENABLED": False,
            "RATELIMIT_ENABLED": False,
        }
    )

    with admin_app.app_context():
        user = User(
            email=email,
            password_hash=PasswordHasher().hash("a-very-strong-test-password"),
            email_verified=True,
        )
        company = Company(name="Restricted Runtime Test", slug=f"runtime-{uuid4().hex}")
        db.session.add_all([user, company])
        db.session.flush()
        user_id, company_id = user.id, company.id
        db.session.add(
            CompanyMembership(
                user_id=user_id, company_id=company_id, role="admin", status="active"
            )
        )
        db.session.commit()

    try:
        client = runtime_app.test_client()
        login_response = client.post(
            "/api/auth/login",
            json={"email": email, "password": "a-very-strong-test-password"},
        )
        assert login_response.status_code == 200

        me_response = client.get("/api/auth/me")
        assert me_response.status_code == 200
        assert me_response.json["authenticated"] is True
        assert [company["id"] for company in me_response.json["companies"]] == [
            str(company_id)
        ]

        select_response = client.post(
            "/api/auth/company", json={"company_id": str(company_id)}
        )
        assert select_response.status_code == 200
        assert select_response.json["selected_company"]["role"] == "admin"
    finally:
        with admin_app.app_context():
            db.session.execute(
                db.delete(Company).where(Company.id == company_id)
            )
            db.session.execute(db.delete(User).where(User.id == user_id))
            db.session.commit()



def test_csrf_token_is_required_for_login():
    application = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "csrf-test-secret",
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
            "WTF_CSRF_ENABLED": True,
            "RATELIMIT_ENABLED": False,
        }
    )
    with application.app_context():
        db.create_all()
        client = application.test_client()
        blocked = client.post(
            "/api/auth/login",
            json={"email": "nobody@example.test", "password": "wrong-password"},
        )
        assert blocked.status_code == 400

        token_response = client.get("/api/auth/csrf")
        token = token_response.json["csrf_token"]
        allowed_through_csrf = client.post(
            "/api/auth/login",
            json={"email": "nobody@example.test", "password": "wrong-password"},
            headers={"X-CSRFToken": token},
        )
        assert allowed_through_csrf.status_code == 401
        db.drop_all()


def test_login_is_rate_limited_per_account_across_different_ips():
    application = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "account-rate-limit-test-secret",
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
            "WTF_CSRF_ENABLED": False,
            "RATELIMIT_ENABLED": True,
            "RATELIMIT_STORAGE_URI": "memory://",
        }
    )
    with application.app_context():
        db.create_all()
        try:
            for index in range(10):
                response = application.test_client().post(
                    "/api/auth/login",
                    json={"email": "target@example.test"},
                    environ_base={"REMOTE_ADDR": f"192.0.2.{index + 1}"},
                )
                assert response.status_code == 400

            blocked = application.test_client().post(
                "/api/auth/login",
                json={"email": "target@example.test"},
                environ_base={"REMOTE_ADDR": "198.51.100.77"},
            )
            assert blocked.status_code == 429
        finally:
            db.session.remove()
            db.drop_all()


def test_incrementing_auth_version_revokes_existing_sessions(app):
    client = app.test_client()
    login_response = client.post(
        "/api/auth/login",
        json={"email": "admin@example.test", "password": "a-very-strong-test-password"},
    )
    assert login_response.status_code == 200
    assert client.get("/api/auth/me").json["authenticated"] is True

    with app.app_context():
        user = db.session.query(User).filter_by(email="admin@example.test").one()
        user.auth_version += 1
        db.session.commit()

    assert client.get("/api/auth/me").json["authenticated"] is False


def test_password_change_requires_current_password_and_revokes_sessions(app):
    client = app.test_client()
    original_password = "a-very-strong-test-password"
    login_response = client.post(
        "/api/auth/login",
        json={"email": "admin@example.test", "password": original_password},
    )
    assert login_response.status_code == 200

    rejected = client.post(
        "/api/auth/password",
        json={
            "current_password": "incorrect-current-password",
            "new_password": "a-different-strong-password",
        },
    )
    assert rejected.status_code == 403

    changed = client.post(
        "/api/auth/password",
        json={
            "current_password": original_password,
            "new_password": "a-different-strong-password",
        },
    )
    assert changed.status_code == 200
    assert changed.json["authenticated"] is False
    assert client.get("/api/auth/me").json["authenticated"] is False

    old_password_login = client.post(
        "/api/auth/login",
        json={"email": "admin@example.test", "password": original_password},
    )
    assert old_password_login.status_code == 401

    new_password_login = client.post(
        "/api/auth/login",
        json={
            "email": "admin@example.test",
            "password": "a-different-strong-password",
        },
    )
    assert new_password_login.status_code == 200


def test_account_without_password_cannot_use_dummy_hash_or_change_password(app):
    with app.app_context():
        passwordless_user = User(
            email="passwordless@example.test",
            display_name="Passwordless User",
            password_hash=None,
        )
        db.session.add(passwordless_user)
        db.session.commit()

    client = app.test_client()
    login_response = client.post(
        "/api/auth/login",
        json={
            "email": "passwordless@example.test",
            "password": "not-a-real-sales-dash-password",
        },
    )
    assert login_response.status_code == 401

    change_response = client.post(
        "/api/auth/password",
        json={
            "current_password": "not-a-real-sales-dash-password",
            "new_password": "a-new-secure-password-value",
        },
    )
    assert change_response.status_code == 401
