import os

from flask import Flask, jsonify, send_from_directory


def create_app(test_config=None):
    """Create and configure the SALES DASH Flask application."""
    app = Flask(
        __name__,
        static_folder="../../frontend",
        static_url_path="/static",
    )

    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY"),
        JSON_SORT_KEYS=False,
    )

    if test_config:
        app.config.update(test_config)

    @app.get("/api/health")
    def health():
        return jsonify({"status": "ok", "service": "sales-dash-api"})

    @app.get("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    return app
