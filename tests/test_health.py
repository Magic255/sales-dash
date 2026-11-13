import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app import create_app


def test_health_endpoint():
    app = create_app({"TESTING": True, "SECRET_KEY": "test-only-secret"})
    response = app.test_client().get("/api/health")

    assert response.status_code == 200
    assert response.get_json() == {
        "status": "ok",
        "service": "sales-dash-api",
    }
