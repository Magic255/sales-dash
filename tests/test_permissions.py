from argon2 import PasswordHasher

from app import create_app
from app.auth import login_required
from app.extensions import db
from app.models import Company, CompanyMembership, User
from app.permissions import ROLE_PERMISSIONS, company_permission_required


def test_role_permission_matrix_is_least_privilege():
    assert "manage_team" in ROLE_PERMISSIONS["admin"]
    assert "manage_team" not in ROLE_PERMISSIONS["manager"]
    assert "delete_sales" not in ROLE_PERMISSIONS["salesperson"]
    assert "create_sales" not in ROLE_PERMISSIONS["viewer"]
    assert "view_dashboard" in ROLE_PERMISSIONS["viewer"]


def test_company_permission_is_enforced_by_server():
    application = create_app({
        "TESTING": True,
        "SECRET_KEY": "permission-test-secret",
        "SQLALCHEMY_DATABASE_URI": "sqlite://",
        "WTF_CSRF_ENABLED": False,
        "RATELIMIT_ENABLED": False,
    })
    with application.app_context():
        db.create_all()
        company = Company(name="Permission Test", slug="permission-test")
        admin = User(
            email="admin@example.test",
            password_hash=PasswordHasher().hash("strong-admin-password"),
        )
        viewer = User(
            email="viewer@example.test",
            password_hash=PasswordHasher().hash("strong-viewer-password"),
        )
        db.session.add_all([company, admin, viewer])
        db.session.flush()
        db.session.add_all([
            CompanyMembership(user_id=admin.id, company_id=company.id, role="admin"),
            CompanyMembership(user_id=viewer.id, company_id=company.id, role="viewer"),
        ])
        company_id = str(company.id)
        db.session.commit()

        @application.get("/api/test/manage-team")
        @login_required
        @company_permission_required("manage_team")
        def manage_team(_user):
            return {"allowed": True}

        @application.get("/api/test/view-dashboard")
        @login_required
        @company_permission_required("view_dashboard")
        def view_dashboard(_user):
            return {"allowed": True}

        try:
            viewer_client = application.test_client()
            viewer_client.post("/api/auth/login", json={
                "email": "viewer@example.test", "password": "strong-viewer-password"
            })
            no_company = viewer_client.get("/api/test/view-dashboard")
            assert no_company.status_code == 409
            selected = viewer_client.post("/api/auth/company", json={"company_id": company_id})
            assert selected.status_code == 200
            assert viewer_client.get("/api/test/view-dashboard").status_code == 200
            assert viewer_client.get("/api/test/manage-team").status_code == 403

            admin_client = application.test_client()
            admin_client.post("/api/auth/login", json={
                "email": "admin@example.test", "password": "strong-admin-password"
            })
            assert admin_client.post(
                "/api/auth/company", json={"company_id": company_id}
            ).status_code == 200
            assert admin_client.get("/api/test/manage-team").status_code == 200
        finally:
            db.session.remove()
            db.drop_all()
