import hashlib
import re
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4

import pytest
from argon2 import PasswordHasher
from sqlalchemy import select

from app import create_app
from app.extensions import db
from app.models import User
from app.password_reset import PasswordResetToken


@pytest.fixture()
def reset_app():
    application = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "password-reset-test-secret",
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
            "WTF_CSRF_ENABLED": False,
            "RATELIMIT_ENABLED": False,
            "PUBLIC_BASE_URL": "https://sales.example.test",
            "MAIL_SERVER": "smtp.gmail.com",
            "MAIL_PORT": 587,
            "MAIL_USE_TLS": True,
            "MAIL_USERNAME": "sender@gmail.com",
            "MAIL_PASSWORD": "test-app-password",
            "MAIL_DEFAULT_SENDER": "sender@gmail.com",
        }
    )
    with application.app_context():
        db.create_all()
        user = User(
            email="reset@example.test",
            password_hash=PasswordHasher().hash("original-strong-password"),
            email_verified=True,
        )
        db.session.add(user)
        db.session.commit()
        yield application
        db.session.remove()
        db.drop_all()


def _token_from_email(mock_send):
    body = mock_send.call_args.args[2]
    match = re.search(r"reset_password=([A-Za-z0-9_-]+)", body)
    assert match
    return match.group(1)


def test_password_reset_request_is_generic_and_stores_only_hash(reset_app):
    client = reset_app.test_client()
    with patch("app.email.send_email") as send:
        known = client.post(
            "/api/auth/password/reset/request", json={"email": " RESET@example.test "}
        )
        unknown = client.post(
            "/api/auth/password/reset/request", json={"email": "missing@example.test"}
        )
    assert known.status_code == unknown.status_code == 200
    assert known.json == unknown.json
    send.assert_called_once()
    raw_token = _token_from_email(send)
    digest = hashlib.sha256(raw_token.encode()).hexdigest()

    with reset_app.app_context():
        stored = db.session.scalar(select(PasswordResetToken))
        assert stored.token_hash == digest
        assert raw_token not in stored.token_hash
        assert stored.expires_at.replace(tzinfo=timezone.utc) > datetime.now(timezone.utc)


def test_password_reset_is_one_time_and_revokes_existing_sessions(reset_app):
    client = reset_app.test_client()
    old_password = "original-strong-password"
    assert client.post(
        "/api/auth/login",
        json={"email": "reset@example.test", "password": old_password},
    ).status_code == 200
    other_session = reset_app.test_client()
    assert other_session.post(
        "/api/auth/login",
        json={"email": "reset@example.test", "password": old_password},
    ).status_code == 200

    with patch("app.email.send_email") as send:
        requested = client.post(
            "/api/auth/password/reset/request", json={"email": "reset@example.test"}
        )
    assert requested.status_code == 200
    token = _token_from_email(send)

    changed = client.post(
        "/api/auth/password/reset/confirm",
        json={"token": token, "new_password": "brand-new-strong-password"},
    )
    assert changed.status_code == 200
    assert changed.json["password_reset"] is True
    assert other_session.get("/api/auth/me").json["authenticated"] is False

    reused = client.post(
        "/api/auth/password/reset/confirm",
        json={"token": token, "new_password": "another-new-strong-password"},
    )
    assert reused.status_code == 400
    assert client.post(
        "/api/auth/login",
        json={"email": "reset@example.test", "password": old_password},
    ).status_code == 401
    assert client.post(
        "/api/auth/login",
        json={"email": "reset@example.test", "password": "brand-new-strong-password"},
    ).status_code == 200


def test_resending_password_reset_invalidates_previous_token(reset_app):
    client = reset_app.test_client()
    with patch("app.email.send_email") as send:
        client.post("/api/auth/password/reset/request", json={"email": "reset@example.test"})
        first = _token_from_email(send)
        client.post("/api/auth/password/reset/request", json={"email": "reset@example.test"})
        second = _token_from_email(send)
    assert first != second
    assert client.post(
        "/api/auth/password/reset/confirm",
        json={"token": first, "new_password": "new-password-should-not-work"},
    ).status_code == 400
    assert client.post(
        "/api/auth/password/reset/confirm",
        json={"token": second, "new_password": "new-password-should-work"},
    ).status_code == 200


def test_expired_password_reset_token_is_rejected(reset_app):
    client = reset_app.test_client()
    with patch("app.email.send_email") as send:
        client.post("/api/auth/password/reset/request", json={"email": "reset@example.test"})
    token = _token_from_email(send)
    with reset_app.app_context():
        stored = db.session.scalar(select(PasswordResetToken))
        stored.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.session.commit()
    response = client.post(
        "/api/auth/password/reset/confirm",
        json={"token": token, "new_password": "new-password-should-not-work"},
    )
    assert response.status_code == 400


def test_password_reset_rejects_short_password_and_malformed_body(reset_app):
    client = reset_app.test_client()
    assert client.post("/api/auth/password/reset/confirm", json=[]).status_code == 400
    assert client.post(
        "/api/auth/password/reset/confirm",
        json={"token": "a" * 40, "new_password": "short"},
    ).status_code == 400


def test_password_reset_requires_verified_active_account(reset_app):
    with reset_app.app_context():
        user = db.session.scalar(select(User).where(User.email == "reset@example.test"))
        user.email_verified = False
        db.session.commit()
    with patch("app.email.send_email") as send:
        response = reset_app.test_client().post(
            "/api/auth/password/reset/request", json={"email": "reset@example.test"}
        )
    assert response.status_code == 200
    send.assert_not_called()


def test_postgres_restricted_runtime_role_can_reset_password():
    import os

    if not os.environ.get("APP_DATABASE_URL") or not os.environ.get("DATABASE_URL"):
        pytest.skip("CI PostgreSQL runtime-role credentials are not configured.")

    email = f"{uuid4()}@example.test"
    admin_app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "reset-admin-test",
            "SQLALCHEMY_DATABASE_URI": os.environ["DATABASE_URL"],
            "WTF_CSRF_ENABLED": False,
        }
    )
    runtime_app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "reset-runtime-test",
            "SQLALCHEMY_DATABASE_URI": os.environ["APP_DATABASE_URL"],
            "WTF_CSRF_ENABLED": False,
            "RATELIMIT_ENABLED": False,
            "PUBLIC_BASE_URL": "https://sales.example.test",
        }
    )
    with admin_app.app_context():
        user = User(
            email=email,
            password_hash=PasswordHasher().hash("original-strong-password"),
            email_verified=True,
        )
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    try:
        client = runtime_app.test_client()
        with patch("app.email.send_email") as send:
            issued = client.post(
                "/api/auth/password/reset/request", json={"email": email}
            )
        assert issued.status_code == 200
        token = _token_from_email(send)
        changed = client.post(
            "/api/auth/password/reset/confirm",
            json={"token": token, "new_password": "brand-new-strong-password"},
        )
        assert changed.status_code == 200
        with admin_app.app_context():
            refreshed = db.session.get(User, user_id)
            assert PasswordHasher().verify(
                refreshed.password_hash, "brand-new-strong-password"
            )
    finally:
        with admin_app.app_context():
            db.session.execute(db.delete(User).where(User.id == user_id))
            db.session.commit()
