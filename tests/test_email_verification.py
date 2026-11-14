import hashlib
import re
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from argon2 import PasswordHasher
from sqlalchemy import select

from app import create_app
from app.email_verification import EmailVerificationToken
from app.extensions import db
from app.models import User


@pytest.fixture()
def verification_app():
    application = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "verification-test-secret",
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
            email="unverified@example.test",
            password_hash=PasswordHasher().hash("a-very-strong-test-password"),
            email_verified=False,
        )
        db.session.add(user)
        db.session.commit()
        yield application
        db.session.remove()
        db.drop_all()


def _token_from_sent_email(mock_send):
    body = mock_send.call_args.args[2]
    match = re.search(r"verify_email=([A-Za-z0-9_-]+)", body)
    assert match
    return match.group(1)


def test_unverified_account_cannot_sign_in(verification_app):
    response = verification_app.test_client().post(
        "/api/auth/login",
        json={
            "email": "unverified@example.test",
            "password": "a-very-strong-test-password",
        },
    )
    assert response.status_code == 401
    assert response.json["error"] == "Email or password is incorrect."


def test_verification_token_is_hashed_one_time_and_expires(verification_app):
    client = verification_app.test_client()
    with patch("app.email.send_email") as send:
        response = client.post(
            "/api/auth/verification/resend",
            json={"email": " UNVERIFIED@example.test "},
        )
    assert response.status_code == 200
    assert response.json == {
        "message": "If the account needs verification, an email will be sent."
    }
    send.assert_called_once()
    raw_token = _token_from_sent_email(send)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()

    with verification_app.app_context():
        stored = db.session.scalar(
            select(EmailVerificationToken).where(
                EmailVerificationToken.user_id
                == db.session.scalar(select(User.id).where(User.email == "unverified@example.test"))
            )
        )
        assert stored.token_hash == token_hash
        assert raw_token not in stored.token_hash
        assert stored.expires_at.replace(tzinfo=timezone.utc) > datetime.now(timezone.utc)

    verified = client.post(
        "/api/auth/verification/confirm", json={"token": raw_token}
    )
    assert verified.status_code == 200
    assert verified.json["email_verified"] is True

    reused = client.post(
        "/api/auth/verification/confirm", json={"token": raw_token}
    )
    assert reused.status_code == 400

    login = client.post(
        "/api/auth/login",
        json={
            "email": "unverified@example.test",
            "password": "a-very-strong-test-password",
        },
    )
    assert login.status_code == 200


def test_resending_invalidates_the_previous_link(verification_app):
    client = verification_app.test_client()
    with patch("app.email.send_email") as send:
        client.post(
            "/api/auth/verification/resend",
            json={"email": "unverified@example.test"},
        )
        first_token = _token_from_sent_email(send)
        client.post(
            "/api/auth/verification/resend",
            json={"email": "unverified@example.test"},
        )
        second_token = _token_from_sent_email(send)

    assert first_token != second_token
    old_link = client.post(
        "/api/auth/verification/confirm", json={"token": first_token}
    )
    assert old_link.status_code == 400
    new_link = client.post(
        "/api/auth/verification/confirm", json={"token": second_token}
    )
    assert new_link.status_code == 200


def test_expired_verification_token_is_rejected(verification_app):
    client = verification_app.test_client()
    with patch("app.email.send_email") as send:
        client.post(
            "/api/auth/verification/resend",
            json={"email": "unverified@example.test"},
        )
    raw_token = _token_from_sent_email(send)
    with verification_app.app_context():
        token = db.session.scalar(select(EmailVerificationToken))
        token.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.session.commit()

    response = client.post(
        "/api/auth/verification/confirm", json={"token": raw_token}
    )
    assert response.status_code == 400


def test_resend_response_does_not_reveal_account_existence(verification_app):
    client = verification_app.test_client()
    with patch("app.email.send_email"):
        known = client.post(
            "/api/auth/verification/resend",
            json={"email": "unverified@example.test"},
        )
        unknown = client.post(
            "/api/auth/verification/resend",
            json={"email": "missing@example.test"},
        )
    assert known.status_code == unknown.status_code == 200
    assert known.json == unknown.json


def test_postgres_restricted_role_can_issue_and_redeem_verification_token():
    import os
    from uuid import uuid4

    if not os.environ.get("APP_DATABASE_URL") or not os.environ.get("DATABASE_URL"):
        pytest.skip("CI PostgreSQL runtime-role credentials are not configured.")

    email = f"{uuid4()}@example.test"
    admin_app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "verification-admin-test",
            "SQLALCHEMY_DATABASE_URI": os.environ["DATABASE_URL"],
            "WTF_CSRF_ENABLED": False,
        }
    )
    runtime_app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "verification-runtime-test",
            "SQLALCHEMY_DATABASE_URI": os.environ["APP_DATABASE_URL"],
            "WTF_CSRF_ENABLED": False,
            "RATELIMIT_ENABLED": False,
            "PUBLIC_BASE_URL": "https://sales.example.test",
        }
    )
    with admin_app.app_context():
        user = User(
            email=email,
            password_hash=PasswordHasher().hash("a-very-strong-test-password"),
            email_verified=False,
        )
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    try:
        client = runtime_app.test_client()
        with patch("app.email.send_email") as send:
            issued = client.post(
                "/api/auth/verification/resend", json={"email": email}
            )
        assert issued.status_code == 200
        raw_token = _token_from_sent_email(send)
        confirmed = client.post(
            "/api/auth/verification/confirm", json={"token": raw_token}
        )
        assert confirmed.status_code == 200

        with admin_app.app_context():
            user = db.session.get(User, user_id)
            assert user.email_verified is True
    finally:
        with admin_app.app_context():
            db.session.execute(db.delete(User).where(User.id == user_id))
            db.session.commit()
