from uuid import uuid4

from app import create_app
from app.extensions import db
from app.models import Company, CompanyMembership, User


def make_provisioning_app(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'provisioning.sqlite'}"
    application = create_app({
        "TESTING": True,
        "SECRET_KEY": "operator-provisioning-test-secret",
        "SQLALCHEMY_DATABASE_URI": database_url,
        "ADMIN_DATABASE_URL": database_url,
        "WTF_CSRF_ENABLED": False,
        "RATELIMIT_ENABLED": False,
    })
    with application.app_context():
        db.create_all()
    return application


def test_create_user_provisions_unverified_account_without_company_access(tmp_path):
    application = make_provisioning_app(tmp_path)
    try:
        result = application.test_cli_runner().invoke(
            args=["create-user"],
            input="new-user@example.test\nNew User\n",
        )
        assert result.exit_code == 0
        assert "Email verification is still required" in result.output
        assert "no company access yet" in result.output.lower()
        with application.app_context():
            user = db.session.scalar(
                db.select(User).where(User.email == "new-user@example.test")
            )
            assert user is not None
            assert user.email_verified is False
            assert user.password_hash
            assert db.session.query(CompanyMembership).filter_by(
                user_id=user.id
            ).count() == 0
    finally:
        with application.app_context():
            db.session.remove()
            db.drop_all()


def test_create_user_rejects_duplicate_email(tmp_path):
    application = make_provisioning_app(tmp_path)
    try:
        with application.app_context():
            db.session.add(User(
                email="existing@example.test",
                display_name="Existing",
                password_hash="already-hashed",
                email_verified=True,
            ))
            db.session.commit()
        result = application.test_cli_runner().invoke(
            args=["create-user"],
            input="existing@example.test\nExisting\n",
        )
        assert result.exit_code != 0
        assert "already exists" in result.output
    finally:
        with application.app_context():
            db.session.remove()
            db.drop_all()


def test_create_company_grants_admin_membership_to_verified_user(tmp_path):
    application = make_provisioning_app(tmp_path)
    user_id = uuid4()
    try:
        with application.app_context():
            db.session.add(User(
                id=user_id,
                email="verified-admin@example.test",
                display_name="Verified Admin",
                password_hash="already-hashed",
                email_verified=True,
            ))
            db.session.commit()
        result = application.test_cli_runner().invoke(
            args=["create-company"],
            input="verified-admin@example.test\nNew Company\n",
        )
        assert result.exit_code == 0
        assert "Company New Company created" in result.output
        with application.app_context():
            company = db.session.scalar(
                db.select(Company).where(Company.name == "New Company")
            )
            assert company is not None
            membership = db.session.get(
                CompanyMembership, (company.id, user_id)
            )
            assert membership.role == "admin"
            assert membership.status == "active"
    finally:
        with application.app_context():
            db.session.remove()
            db.drop_all()


def test_create_company_rejects_unverified_account(tmp_path):
    application = make_provisioning_app(tmp_path)
    try:
        with application.app_context():
            db.session.add(User(
                email="unverified-admin@example.test",
                display_name="Unverified",
                password_hash="already-hashed",
                email_verified=False,
            ))
            db.session.commit()
        result = application.test_cli_runner().invoke(
            args=["create-company"],
            input="unverified-admin@example.test\nBlocked Company\n",
        )
        assert result.exit_code != 0
        assert "verified email" in result.output
        with application.app_context():
            assert db.session.query(Company).filter_by(name="Blocked Company").count() == 0
    finally:
        with application.app_context():
            db.session.remove()
            db.drop_all()
