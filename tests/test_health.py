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


def test_health_endpoint():
    response = create_test_client().get("/api/health")

    assert response.status_code == 200
    assert response.get_json() == {
        "status": "ok",
        "service": "sales-dash-api",
    }


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
