import os

from flask import Flask, jsonify, send_from_directory

from .config import Config


def create_app(test_config=None):
    """Create and configure the SALES DASH Flask application."""
    frontend_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "frontend")
    )

    app = Flask(
        __name__,
        static_folder=frontend_dir,
        static_url_path="/static",
    )
    app.config.from_object(Config)

    if test_config:
        app.config.update(test_config)

    @app.get("/api/health")
    def health():
        return jsonify({"status": "ok", "service": "sales-dash-api"})

    @app.get("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    return app
