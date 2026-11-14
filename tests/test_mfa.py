import hashlib

import pyotp
import pytest
from argon2 import PasswordHasher
from cryptography.fernet import Fernet
from sqlalchemy import select

from app import create_app
from app.extensions import db
from app.mfa_models import MfaCredential, MfaRecoveryCode
from app.models import User


@pytest.fixture()
def mfa_app():
    application = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "mfa-test-secret",
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
            "WTF_CSRF_ENABLED": False,
            "RATELIMIT_ENABLED": False,
            "MFA_ENCRYPTION_KEY": Fernet.generate_key().decode(),
        }
    )
    with application.app_context():
        db.create_all()
        db.session.add(
            User(
                email="mfa-user@example.test",
                password_hash=PasswordHasher().hash("a-very-strong-test-password"),
                email_verified=True,
            )
        )
        db.session.commit()
        yield application
        db.session.remove()
        db.drop_all()


def _client(mfa_app):
    client = mfa_app.test_client()
    response = client.post(
        "/api/auth/login",
        json={
            "email": "mfa-user@example.test",
            "password": "a-very-strong-test-password",
        },
    )
    assert response.status_code == 200
    return client


def _enable_mfa(client):
    setup = client.post(
        "/api/auth/mfa/setup",
        json={"current_password": "a-very-strong-test-password"},
    )
    assert setup.status_code == 200
    secret = setup.json["secret"]
    confirmation = client.post(
        "/api/auth/mfa/confirm",
        json={"code": pyotp.TOTP(secret).now()},
    )
    assert confirmation.status_code == 200
    return secret, confirmation.json["recovery_codes"]


def test_mfa_setup_encrypts_secret_and_shows_recovery_codes_once(mfa_app):
    client = _client(mfa_app)
    rejected = client.post(
        "/api/auth/mfa/setup", json={"current_password": "wrong-password"}
    )
    assert rejected.status_code == 403

    setup = client.post(
        "/api/auth/mfa/setup",
        json={"current_password": "a-very-strong-test-password"},
    )
    assert setup.status_code == 200
    secret = setup.json["secret"]
    assert setup.json["provisioning_uri"].startswith("otpauth://totp/")

    with mfa_app.app_context():
        credential = db.session.scalar(select(MfaCredential))
        assert credential.secret_ciphertext != secret
        assert Fernet(mfa_app.config["MFA_ENCRYPTION_KEY"].encode()).decrypt(
            credential.secret_ciphertext.encode()
        ).decode() == secret

    invalid = client.post("/api/auth/mfa/confirm", json={"code": "abc123"})
    assert invalid.status_code == 400
    confirmed = client.post(
        "/api/auth/mfa/confirm", json={"code": pyotp.TOTP(secret).now()}
    )
    assert confirmed.status_code == 200
    codes = confirmed.json["recovery_codes"]
    assert len(codes) == 10
    assert client.get("/api/auth/mfa/status").json["enabled"] is True

    with mfa_app.app_context():
        stored_hashes = db.session.scalars(
            select(MfaRecoveryCode.code_hash)
        ).all()
        assert len(stored_hashes) == 10
        assert all(
            hashlib.sha256(code.replace("-", "").encode()).hexdigest() in stored_hashes
            for code in codes
        )


def test_login_requires_mfa_and_recovery_codes_are_single_use(mfa_app):
    client = _client(mfa_app)
    _secret, recovery_codes = _enable_mfa(client)
    client.post("/api/auth/logout")

    login = client.post(
        "/api/auth/login",
        json={
            "email": "mfa-user@example.test",
            "password": "a-very-strong-test-password",
        },
    )
    assert login.status_code == 200
    assert login.json == {"mfa_required": True}
    assert client.get("/api/auth/me").json["authenticated"] is False

    accepted = client.post(
        "/api/auth/mfa/challenge", json={"code": recovery_codes[0]}
    )
    assert accepted.status_code == 200
    assert client.get("/api/auth/me").json["authenticated"] is True

    client.post("/api/auth/logout")
    second_login = client.post(
        "/api/auth/login",
        json={
            "email": "mfa-user@example.test",
            "password": "a-very-strong-test-password",
        },
    )
    assert second_login.json == {"mfa_required": True}
    replay = client.post(
        "/api/auth/mfa/challenge", json={"code": recovery_codes[0]}
    )
    assert replay.status_code == 401
    accepted_second = client.post(
        "/api/auth/mfa/challenge", json={"code": recovery_codes[1]}
    )
    assert accepted_second.status_code == 200


def test_disabling_mfa_requires_password_and_second_factor_and_revokes_session(mfa_app):
    client = _client(mfa_app)
    _secret, recovery_codes = _enable_mfa(client)

    wrong_password = client.post(
        "/api/auth/mfa/disable",
        json={"current_password": "wrong-password", "code": recovery_codes[0]},
    )
    assert wrong_password.status_code == 403

    disabled = client.post(
        "/api/auth/mfa/disable",
        json={
            "current_password": "a-very-strong-test-password",
            "code": recovery_codes[0],
        },
    )
    assert disabled.status_code == 200
    assert disabled.json["authenticated"] is False
    assert client.get("/api/auth/me").json["authenticated"] is False

    login = client.post(
        "/api/auth/login",
        json={
            "email": "mfa-user@example.test",
            "password": "a-very-strong-test-password",
        },
    )
    assert login.status_code == 200
    assert login.json == {"authenticated": True}


def test_totp_time_step_cannot_be_reused_for_two_logins(mfa_app):
    from datetime import datetime, timedelta, timezone

    client = _client(mfa_app)
    secret, _recovery_codes = _enable_mfa(client)
    future_code = pyotp.TOTP(secret).at(
        datetime.now(timezone.utc) + timedelta(seconds=30)
    )
    client.post("/api/auth/logout")

    first_login = client.post(
        "/api/auth/login",
        json={
            "email": "mfa-user@example.test",
            "password": "a-very-strong-test-password",
        },
    )
    assert first_login.json == {"mfa_required": True}
    assert client.post(
        "/api/auth/mfa/challenge", json={"code": future_code}
    ).status_code == 200

    client.post("/api/auth/logout")
    second_login = client.post(
        "/api/auth/login",
        json={
            "email": "mfa-user@example.test",
            "password": "a-very-strong-test-password",
        },
    )
    assert second_login.json == {"mfa_required": True}
    replay = client.post(
        "/api/auth/mfa/challenge", json={"code": future_code}
    )
    assert replay.status_code == 401
