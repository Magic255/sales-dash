import hashlib
import re
from unittest.mock import patch
from uuid import uuid4

import pytest
from argon2 import PasswordHasher
from sqlalchemy import select

from app import create_app
from app.company_invitation import CompanyInvitation
from app.extensions import db
from app.models import Company, CompanyMembership, User


@pytest.fixture()
def invitation_app():
    application = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "company-invitation-test-secret",
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
        admin = User(
            email="admin@example.test",
            password_hash=PasswordHasher().hash("original-admin-password"),
            email_verified=True,
        )
        invitee = User(
            email="invitee@example.test",
            password_hash=PasswordHasher().hash("original-invitee-password"),
            email_verified=True,
        )
        manager = User(
            email="manager@example.test",
            password_hash=PasswordHasher().hash("original-manager-password"),
            email_verified=True,
        )
        company = Company(name="Invitation Company", slug="invitation-company")
        db.session.add_all([admin, invitee, manager, company])
        db.session.flush()
        db.session.add_all(
            [
                CompanyMembership(
                    user_id=admin.id, company_id=company.id, role="admin", status="active"
                ),
                CompanyMembership(
                    user_id=manager.id,
                    company_id=company.id,
                    role="manager",
                    status="active",
                ),
            ]
        )
        db.session.commit()
        yield application
        db.session.remove()
        db.drop_all()


def _client_for(application, email, password):
    client = application.test_client()
    response = client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert response.status_code == 200
    return client


def _admin_client(application):
    client = _client_for(application, "admin@example.test", "original-admin-password")
    with application.app_context():
        company_id = str(
            db.session.scalar(select(Company.id).where(Company.slug == "invitation-company"))
        )
    selected = client.post("/api/auth/company", json={"company_id": company_id})
    assert selected.status_code == 200
    return client


def _token_from_email(mock_send):
    body = mock_send.call_args.args[2]
    match = re.search(r"accept_invitation=([A-Za-z0-9_-]+)", body)
    assert match
    return match.group(1)


def test_admin_invites_verified_account_and_invitee_accepts_once(invitation_app):
    admin = _admin_client(invitation_app)
    with patch("app.email.send_email") as send:
        response = admin.post(
            "/api/team/invitations",
            json={"email": " INVITEE@example.test ", "role": "salesperson"},
        )
    assert response.status_code == 201
    send.assert_called_once()
    raw_token = _token_from_email(send)
    digest = hashlib.sha256(raw_token.encode()).hexdigest()

    with invitation_app.app_context():
        invitation = db.session.scalar(select(CompanyInvitation))
        assert invitation.token_hash == digest
        assert raw_token not in invitation.token_hash
        assert invitation.role == "salesperson"

    pending = admin.get("/api/team/invitations")
    assert pending.status_code == 200
    assert pending.json["items"][0]["email"] == "invitee@example.test"

    invitee = _client_for(
        invitation_app, "invitee@example.test", "original-invitee-password"
    )
    accepted = invitee.post(
        "/api/team/invitations/accept", json={"token": raw_token}
    )
    assert accepted.status_code == 200
    assert accepted.json["accepted"] is True

    membership = invitee.get("/api/auth/me")
    assert membership.status_code == 200
    assert any(
        item["role"] == "salesperson" for item in membership.json["companies"]
    )

    replay = invitee.post(
        "/api/team/invitations/accept", json={"token": raw_token}
    )
    assert replay.status_code == 400


def test_invitation_is_bound_to_exact_verified_email(invitation_app):
    admin = _admin_client(invitation_app)
    with patch("app.email.send_email") as send:
        admin.post(
            "/api/team/invitations",
            json={"email": "invitee@example.test", "role": "viewer"},
        )
    token = _token_from_email(send)
    wrong_user = admin
    rejected = wrong_user.post(
        "/api/team/invitations/accept", json={"token": token}
    )
    assert rejected.status_code == 400

    invitee = _client_for(
        invitation_app, "invitee@example.test", "original-invitee-password"
    )
    accepted = invitee.post(
        "/api/team/invitations/accept", json={"token": token}
    )
    assert accepted.status_code == 200


def test_revoked_invitation_cannot_be_accepted(invitation_app):
    admin = _admin_client(invitation_app)
    with patch("app.email.send_email") as send:
        admin.post(
            "/api/team/invitations",
            json={"email": "invitee@example.test", "role": "viewer"},
        )
    token = _token_from_email(send)
    with invitation_app.app_context():
        invitation_id = str(db.session.scalar(select(CompanyInvitation.id)))
    revoked = admin.delete(f"/api/team/invitations/{invitation_id}")
    assert revoked.status_code == 200

    invitee = _client_for(
        invitation_app, "invitee@example.test", "original-invitee-password"
    )
    rejected = invitee.post(
        "/api/team/invitations/accept", json={"token": token}
    )
    assert rejected.status_code == 400


def test_only_company_admin_can_send_invitations(invitation_app):
    manager = _client_for(
        invitation_app, "manager@example.test", "original-manager-password"
    )
    with invitation_app.app_context():
        company_id = str(
            db.session.scalar(select(Company.id).where(Company.slug == "invitation-company"))
        )
    assert manager.post(
        "/api/auth/company", json={"company_id": company_id}
    ).status_code == 200
    response = manager.post(
        "/api/team/invitations",
        json={"email": "invitee@example.test", "role": "viewer"},
    )
    assert response.status_code == 403


def test_unknown_or_unverified_accounts_receive_no_invitation(invitation_app):
    admin = _admin_client(invitation_app)
    with patch("app.email.send_email") as send:
        unknown = admin.post(
            "/api/team/invitations",
            json={"email": "missing@example.test", "role": "viewer"},
        )
        assert unknown.status_code == 200
        assert "If this is an active" in unknown.json["message"]

        with invitation_app.app_context():
            unverified = User(
                email="unverified@example.test",
                password_hash=PasswordHasher().hash("unverified-account-password"),
                email_verified=False,
            )
            db.session.add(unverified)
            db.session.commit()

        unverified_response = admin.post(
            "/api/team/invitations",
            json={"email": "unverified@example.test", "role": "viewer"},
        )
        assert unverified_response.status_code == 200
        send.assert_not_called()


def test_invitation_rejects_admin_role_and_malformed_payload(invitation_app):
    admin = _admin_client(invitation_app)
    assert admin.post("/api/team/invitations", json=[]).status_code == 400
    assert admin.post(
        "/api/team/invitations",
        json={"email": "invitee@example.test", "role": "admin"},
    ).status_code == 400


def test_postgres_restricted_runtime_role_can_create_and_accept_invitation():
    import os

    if not os.environ.get("APP_DATABASE_URL") or not os.environ.get("DATABASE_URL"):
        pytest.skip("CI PostgreSQL runtime-role credentials are not configured.")

    email = f"{uuid4()}@example.test"
    admin_app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "invitation-admin-test",
            "SQLALCHEMY_DATABASE_URI": os.environ["DATABASE_URL"],
            "WTF_CSRF_ENABLED": False,
        }
    )
    runtime_app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "invitation-runtime-test",
            "SQLALCHEMY_DATABASE_URI": os.environ["APP_DATABASE_URL"],
            "WTF_CSRF_ENABLED": False,
            "RATELIMIT_ENABLED": False,
            "PUBLIC_BASE_URL": "https://sales.example.test",
        }
    )
    admin_password = "original-admin-password"
    invitee_password = "original-invitee-password"
    with admin_app.app_context():
        admin = User(
            email=f"admin-{uuid4()}@example.test",
            password_hash=PasswordHasher().hash(admin_password),
            email_verified=True,
        )
        invitee = User(
            email=email,
            password_hash=PasswordHasher().hash(invitee_password),
            email_verified=True,
        )
        company = Company(name="Restricted Invitation", slug=f"invite-{uuid4().hex}")
        db.session.add_all([admin, invitee, company])
        db.session.flush()
        admin_id, invitee_id, company_id = admin.id, invitee.id, company.id
        admin_email = admin.email
        db.session.add(
            CompanyMembership(
                user_id=admin_id, company_id=company_id, role="admin", status="active"
            )
        )
        db.session.commit()

    try:
        admin_client = _client_for(runtime_app, admin_email, admin_password)
        assert admin_client.post(
            "/api/auth/company", json={"company_id": str(company_id)}
        ).status_code == 200
        with patch("app.email.send_email") as send:
            created = admin_client.post(
                "/api/team/invitations",
                json={"email": email, "role": "manager"},
            )
        assert created.status_code == 201
        token = _token_from_email(send)

        invitee_client = _client_for(runtime_app, email, invitee_password)
        accepted = invitee_client.post(
            "/api/team/invitations/accept", json={"token": token}
        )
        assert accepted.status_code == 200
        assert any(
            item["id"] == str(company_id) and item["role"] == "manager"
            for item in invitee_client.get("/api/auth/me").json["companies"]
        )
    finally:
        with admin_app.app_context():
            db.session.execute(db.delete(Company).where(Company.id == company_id))
            db.session.execute(db.delete(User).where(User.id == admin_id))
            db.session.execute(db.delete(User).where(User.id == invitee_id))
            db.session.commit()
