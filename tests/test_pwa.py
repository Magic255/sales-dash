import json

from app import create_app


def create_test_client():
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-only-secret",
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
        }
    )
    return app.test_client()


def test_service_worker_is_available_at_root_scope():
    response = create_test_client().get("/service-worker.js")

    assert response.status_code == 200
    assert response.headers["Service-Worker-Allowed"] == "/"
    assert b'url.pathname.startsWith("/api/")' in response.data
    assert b'cache.addAll(SHELL_ASSETS)' in response.data


def test_pwa_manifest_is_valid_and_has_app_icon():
    response = create_test_client().get("/manifest.webmanifest")

    assert response.status_code == 200
    manifest = json.loads(response.data)
    assert manifest["start_url"] == "/"
    assert manifest["scope"] == "/"
    assert manifest["display"] == "standalone"
    assert manifest["icons"][0]["src"] == "/static/icon.svg"


def test_pwa_frontend_assets_are_served():
    client = create_test_client()

    assert client.get("/static/pwa.js").status_code == 200
    assert client.get("/static/icon.svg").status_code == 200


def test_private_api_responses_are_never_cached():
    response = create_test_client().get("/api/health")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
