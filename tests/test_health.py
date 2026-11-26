import pytest
from cryptography.fernet import Fernet

from app import create_app
from app.extensions import db, migrate


def create_test_client():
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-only-secret",
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
        }
    )
    return app.test_client()


def test_health_endpoint_checks_database_and_disables_caching():
    response = create_test_client().get("/api/health")

    assert response.status_code == 200
    assert response.get_json() == {
        "status": "ok",
        "service": "sales-dash-api",
    }
    assert response.headers["Cache-Control"] == "no-store"


def test_health_endpoint_returns_unavailable_when_database_check_fails(monkeypatch):
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-only-secret",
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
        }
    )

    def fail_database_check(_statement):
        raise RuntimeError("database unavailable")

    with app.app_context():
        monkeypatch.setattr(db.engine, "connect", fail_database_check)
        response = app.test_client().get("/api/health")

    assert response.status_code == 503
    assert response.get_json() == {
        "status": "unavailable",
        "service": "sales-dash-api",
    }
    assert response.headers["Cache-Control"] == "no-store"


def test_production_requires_mfa_encryption_key():
    with pytest.raises(RuntimeError, match="MFA_ENCRYPTION_KEY must be set"):
        create_app(
            {
                "TESTING": True,
                "APP_ENV": "production",
                "SECRET_KEY": "production-test-secret",
                "RATELIMIT_STORAGE_URI": "redis://localhost:6379/0",
                "MFA_ENCRYPTION_KEY": None,
                "COMPLIANCE_EVIDENCE_ENCRYPTION_KEY": Fernet.generate_key().decode(),
                "SQLALCHEMY_DATABASE_URI": "sqlite://",
            }
        )


def test_production_rejects_invalid_mfa_encryption_key():
    with pytest.raises(RuntimeError, match="valid Fernet key"):
        create_app(
            {
                "TESTING": True,
                "APP_ENV": "production",
                "SECRET_KEY": "production-test-secret",
                "RATELIMIT_STORAGE_URI": "redis://localhost:6379/0",
                "MFA_ENCRYPTION_KEY": "not-a-valid-fernet-key",
                "COMPLIANCE_EVIDENCE_ENCRYPTION_KEY": Fernet.generate_key().decode(),
                "SQLALCHEMY_DATABASE_URI": "sqlite://",
            }
        )


def test_production_accepts_valid_mfa_encryption_key():
    app = create_app(
        {
            "TESTING": True,
            "APP_ENV": "production",
            "SECRET_KEY": "production-test-secret",
            "RATELIMIT_STORAGE_URI": "redis://localhost:6379/0",
            "MFA_ENCRYPTION_KEY": Fernet.generate_key().decode(),
            "COMPLIANCE_EVIDENCE_ENCRYPTION_KEY": Fernet.generate_key().decode(),
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
        }
    )

    assert app.config["APP_ENV"] == "production"


def test_production_requires_compliance_evidence_encryption_key():
    with pytest.raises(RuntimeError, match="COMPLIANCE_EVIDENCE_ENCRYPTION_KEY must be set"):
        create_app(
            {
                "TESTING": True,
                "APP_ENV": "production",
                "SECRET_KEY": "production-test-secret",
                "RATELIMIT_STORAGE_URI": "redis://localhost:6379/0",
                "MFA_ENCRYPTION_KEY": Fernet.generate_key().decode(),
                "COMPLIANCE_EVIDENCE_ENCRYPTION_KEY": None,
                "SQLALCHEMY_DATABASE_URI": "sqlite://",
            }
        )


def test_production_rejects_invalid_compliance_evidence_encryption_key():
    with pytest.raises(RuntimeError, match="COMPLIANCE_EVIDENCE_ENCRYPTION_KEY must be a valid Fernet key"):
        create_app(
            {
                "TESTING": True,
                "APP_ENV": "production",
                "SECRET_KEY": "production-test-secret",
                "RATELIMIT_STORAGE_URI": "redis://localhost:6379/0",
                "MFA_ENCRYPTION_KEY": Fernet.generate_key().decode(),
                "COMPLIANCE_EVIDENCE_ENCRYPTION_KEY": "invalid-evidence-key",
                "SQLALCHEMY_DATABASE_URI": "sqlite://",
            }
        )


def test_production_requires_distinct_mfa_and_evidence_keys():
    shared_key = Fernet.generate_key().decode()
    with pytest.raises(RuntimeError, match="must be distinct"):
        create_app(
            {
                "TESTING": True,
                "APP_ENV": "production",
                "SECRET_KEY": "production-test-secret",
                "RATELIMIT_STORAGE_URI": "redis://localhost:6379/0",
                "MFA_ENCRYPTION_KEY": shared_key,
                "COMPLIANCE_EVIDENCE_ENCRYPTION_KEY": shared_key,
                "SQLALCHEMY_DATABASE_URI": "sqlite://",
            }
        )


def test_production_requires_explicit_app_database_url(monkeypatch):
    monkeypatch.delenv("APP_DATABASE_URL", raising=False)

    with pytest.raises(RuntimeError, match="APP_DATABASE_URL must be set explicitly"):
        create_app(
            {
                "TESTING": False,
                "APP_ENV": "production",
                "SECRET_KEY": "production-test-secret",
                "RATELIMIT_STORAGE_URI": "redis://localhost:6379/0",
                "MFA_ENCRYPTION_KEY": Fernet.generate_key().decode(),
                "SQLALCHEMY_DATABASE_URI": "postgresql+psycopg://runtime:secret@db/app",
            }
        )


def test_production_rejects_non_postgres_runtime_database(monkeypatch):
    monkeypatch.setenv(
        "APP_DATABASE_URL", "postgresql+psycopg://runtime:secret@db/app"
    )

    with pytest.raises(RuntimeError, match="Production requires APP_DATABASE_URL"):
        create_app(
            {
                "TESTING": False,
                "APP_ENV": "production",
                "SECRET_KEY": "production-test-secret",
                "RATELIMIT_STORAGE_URI": "redis://localhost:6379/0",
                "MFA_ENCRYPTION_KEY": Fernet.generate_key().decode(),
                "SQLALCHEMY_DATABASE_URI": "sqlite://",
            }
        )


def test_homepage_is_served():
    response = create_test_client().get("/")

    assert response.status_code == 200
    assert b"SALES DASH" in response.data


def test_frontend_stylesheet_is_served():
    response = create_test_client().get("/static/styles.css")

    assert response.status_code == 200
    assert b"font-family" in response.data


def test_database_and_migrations_are_registered():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite://"})

    assert "sqlalchemy" in app.extensions
    assert "migrate" in app.extensions
    assert db is not None
    assert migrate is not None
