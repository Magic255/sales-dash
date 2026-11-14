from uuid import uuid4

import pytest
from argon2 import PasswordHasher

from app import create_app
from app.extensions import db
from app.models import AuditLog, Company, CompanyMembership, User


def make_team_client():
    application = create_app({
        "TESTING": True,
        "SECRET_KEY": "team-management-test-secret",
        "SQLALCHEMY_DATABASE_URI": "sqlite://",
        "WTF_CSRF_ENABLED": False,
        "RATELIMIT_ENABLED": False,
    })
    with application.app_context():
        db.create_all()
        admin = User(
            email="admin@team.example.test",
            password_hash=PasswordHasher().hash("a-very-strong-test-password"),
            email_verified=True,
        )
        member = User(
            email="member@team.example.test",
            display_name="Team Member",
            password_hash=PasswordHasher().hash("another-strong-test-password"),
            email_verified=True,
        )
        company = Company(name="Team Company", slug=f"team-{uuid4().hex}")
        db.session.add_all([admin, member, company])
        db.session.flush()
        db.session.add_all([
            CompanyMembership(
                user_id=admin.id, company_id=company.id, role="admin", status="active"
            ),
            CompanyMembership(
                user_id=member.id, company_id=company.id, role="salesperson", status="active"
            ),
        ])
        admin_id, member_id, company_id = admin.id, member.id, company.id
        db.session.commit()

    client = application.test_client()
    assert client.post("/api/auth/login", json={
        "email": "admin@team.example.test",
        "password": "a-very-strong-test-password",
    }).status_code == 200
    assert client.post(
        "/api/auth/company", json={"company_id": str(company_id)}
    ).status_code == 200
    return application, client, admin_id, member_id, company_id


def test_admin_can_list_members_change_role_and_suspend_or_reactivate():
    application, client, _admin_id, member_id, _company_id = make_team_client()
    try:
        listed = client.get("/api/team/members")
        assert listed.status_code == 200
        assert len(listed.json["items"]) == 2
        member = next(item for item in listed.json["items"] if item["user_id"] == str(member_id))
        assert member["email"] == "member@team.example.test"
        assert member["display_name"] == "Team Member"
        assert member["role"] == "salesperson"
        assert member["status"] == "active"

        changed = client.patch(
            f"/api/team/members/{member_id}", json={"role": "manager"}
        )
        assert changed.status_code == 200
        assert changed.json["item"]["role"] == "manager"

        suspended = client.patch(
            f"/api/team/members/{member_id}", json={"status": "suspended"}
        )
        assert suspended.status_code == 200
        assert suspended.json["item"]["status"] == "suspended"

        reactivated = client.patch(
            f"/api/team/members/{member_id}", json={"status": "active"}
        )
        assert reactivated.status_code == 200
        assert reactivated.json["item"]["status"] == "active"

        with application.app_context():
            events = db.session.query(AuditLog).filter(
                AuditLog.event_type.in_([
                    "team_member_role_changed",
                    "team_member_suspended",
                    "team_member_reactivated",
                ])
            ).all()
            assert len(events) == 3
    finally:
        with application.app_context():
            db.session.remove()
            db.drop_all()


def test_non_admin_cannot_list_or_manage_company_members():
    application, client, _admin_id, member_id, company_id = make_team_client()
    try:
        assert client.post("/api/auth/logout").status_code == 200
        assert client.post("/api/auth/login", json={
            "email": "member@team.example.test",
            "password": "another-strong-test-password",
        }).status_code == 200
        assert client.post(
            "/api/auth/company", json={"company_id": str(company_id)}
        ).status_code == 200
        assert client.get("/api/team/members").status_code == 403
        assert client.patch(
            f"/api/team/members/{member_id}", json={"role": "viewer"}
        ).status_code == 403
    finally:
        with application.app_context():
            db.session.remove()
            db.drop_all()


def test_admin_cannot_change_own_membership_or_another_admin():
    application, client, admin_id, _member_id, company_id = make_team_client()
    try:
        self_change = client.patch(
            f"/api/team/members/{admin_id}", json={"status": "suspended"}
        )
        assert self_change.status_code == 409
        with application.app_context():
            other_admin = User(
                email="second-admin@team.example.test",
                password_hash=PasswordHasher().hash("a-second-strong-password"),
                email_verified=True,
            )
            db.session.add(other_admin)
            db.session.flush()
            db.session.add(CompanyMembership(
                user_id=other_admin.id, company_id=company_id,
                role="admin", status="active",
            ))
            second_admin_id = other_admin.id
            db.session.commit()
        protected = client.patch(
            f"/api/team/members/{second_admin_id}", json={"role": "viewer"}
        )
        assert protected.status_code == 409
        with application.app_context():
            membership = db.session.get(
                CompanyMembership, (company_id, second_admin_id)
            )
            assert membership.role == "admin"
            assert membership.status == "active"
    finally:
        with application.app_context():
            db.session.remove()
            db.drop_all()


def test_member_management_rejects_invalid_payloads_and_roles():
    application, client, _admin_id, member_id, _company_id = make_team_client()
    try:
        payloads = (
            [], {}, {"role": "admin"}, {"role": "owner"}, {"status": "invited"},
            {"role": "viewer", "status": "active"}, {"status": "deleted"},
        )
        for payload in payloads:
            response = client.patch(f"/api/team/members/{member_id}", json=payload)
            assert response.status_code == 400
    finally:
        with application.app_context():
            db.session.remove()
            db.drop_all()


def test_suspension_removes_access_on_next_company_request():
    application, client, _admin_id, member_id, company_id = make_team_client()
    try:
        assert client.patch(
            f"/api/team/members/{member_id}", json={"status": "suspended"}
        ).status_code == 200
        member_client = application.test_client()
        assert member_client.post("/api/auth/login", json={
            "email": "member@team.example.test",
            "password": "another-strong-test-password",
        }).status_code == 200
        assert member_client.post(
            "/api/auth/company", json={"company_id": str(company_id)}
        ).status_code == 403
    finally:
        with application.app_context():
            db.session.remove()
            db.drop_all()


def test_postgres_restricted_runtime_role_can_manage_company_members():
    import os

    if not os.environ.get("APP_DATABASE_URL") or not os.environ.get("DATABASE_URL"):
        pytest.skip("CI PostgreSQL runtime-role credentials are not configured.")

    admin_app = create_app({
        "TESTING": True,
        "SECRET_KEY": "team-management-admin-test",
        "SQLALCHEMY_DATABASE_URI": os.environ["DATABASE_URL"],
        "WTF_CSRF_ENABLED": False,
    })
    runtime_app = create_app({
        "TESTING": True,
        "SECRET_KEY": "team-management-runtime-test",
        "SQLALCHEMY_DATABASE_URI": os.environ["APP_DATABASE_URL"],
        "WTF_CSRF_ENABLED": False,
        "RATELIMIT_ENABLED": False,
    })
    admin_email = f"admin-{uuid4()}@example.test"
    member_email = f"member-{uuid4()}@example.test"
    with admin_app.app_context():
        admin = User(
            email=admin_email,
            password_hash=PasswordHasher().hash("a-very-strong-test-password"),
            email_verified=True,
        )
        member = User(
            email=member_email,
            display_name="Postgres Member",
            password_hash=PasswordHasher().hash("another-strong-test-password"),
            email_verified=True,
        )
        company = Company(name="Restricted Team", slug=f"team-{uuid4().hex}")
        db.session.add_all([admin, member, company])
        db.session.flush()
        db.session.add_all([
            CompanyMembership(
                user_id=admin.id, company_id=company.id, role="admin", status="active"
            ),
            CompanyMembership(
                user_id=member.id, company_id=company.id, role="salesperson", status="active"
            ),
        ])
        admin_id, member_id, company_id = admin.id, member.id, company.id
        db.session.commit()

    try:
        client = runtime_app.test_client()
        assert client.post("/api/auth/login", json={
            "email": admin_email, "password": "a-very-strong-test-password"
        }).status_code == 200
        selected = client.post(
            "/api/auth/company", json={"company_id": str(company_id)}
        )
        assert selected.status_code == 200
        roster = client.get("/api/team/members")
        assert roster.status_code == 200
        assert any(item["user_id"] == str(member_id) for item in roster.json["items"])
        updated = client.patch(
            f"/api/team/members/{member_id}", json={"role": "manager"}
        )
        assert updated.status_code == 200
        assert updated.json["item"]["role"] == "manager"
        suspended = client.patch(
            f"/api/team/members/{member_id}", json={"status": "suspended"}
        )
        assert suspended.status_code == 200
    finally:
        with admin_app.app_context():
            db.session.execute(db.delete(Company).where(Company.id == company_id))
            db.session.execute(db.delete(User).where(User.id.in_([admin_id, member_id])))
            db.session.commit()
