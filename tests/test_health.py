import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app import create_app


def create_test_client():
    app = create_app({"TESTING": True, "SECRET_KEY": "test-only-secret"})
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
