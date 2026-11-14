import pytest
import pyotp
from argon2 import PasswordHasher
from cryptography.fernet import Fernet

from app import create_app
from app.extensions import db
from app.models import User


def test_postgres_restricted_runtime_role_can_enroll_and_use_mfa():
    import os
    from uuid import uuid4

    if not os.environ.get("APP_DATABASE_URL") or not os.environ.get("DATABASE_URL"):
        pytest.skip("CI PostgreSQL runtime-role credentials are not configured.")

    email = f"{uuid4()}@example.test"
    encryption_key = Fernet.generate_key().decode()
    admin_app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "mfa-admin-test-secret",
            "SQLALCHEMY_DATABASE_URI": os.environ["DATABASE_URL"],
            "WTF_CSRF_ENABLED": False,
        }
    )
    runtime_app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "mfa-runtime-test-secret",
            "SQLALCHEMY_DATABASE_URI": os.environ["APP_DATABASE_URL"],
            "WTF_CSRF_ENABLED": False,
            "RATELIMIT_ENABLED": False,
            "MFA_ENCRYPTION_KEY": encryption_key,
        }
    )
    password = "a-very-strong-test-password"
    with admin_app.app_context():
        user = User(
            email=email,
            password_hash=PasswordHasher().hash(password),
            email_verified=True,
        )
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    try:
        client = runtime_app.test_client()
        login = client.post("/api/auth/login", json={"email": email, "password": password})
        assert login.status_code == 200
        setup = client.post("/api/auth/mfa/setup", json={"current_password": password})
        assert setup.status_code == 200
        confirmation = client.post(
            "/api/auth/mfa/confirm",
            json={"code": pyotp.TOTP(setup.json["secret"]).now()},
        )
        assert confirmation.status_code == 200
        recovery_code = confirmation.json["recovery_codes"][0]
        client.post("/api/auth/logout")

        second_login = client.post(
            "/api/auth/login", json={"email": email, "password": password}
        )
        assert second_login.json == {"mfa_required": True}
        challenge = client.post(
            "/api/auth/mfa/challenge", json={"code": recovery_code}
        )
        assert challenge.status_code == 200
        assert client.get("/api/auth/me").json["authenticated"] is True
    finally:
        with admin_app.app_context():
            db.session.execute(db.delete(User).where(User.id == user_id))
            db.session.commit()
