import os

from flask import Flask, jsonify, request, send_from_directory
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFError, CSRFProtect

from . import models  # noqa: F401 - register model metadata for Alembic
from .commands import register_commands
from .config import Config
from .extensions import db, migrate

csrf = CSRFProtect()
limiter = Limiter(key_func=get_remote_address)


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

    if not app.testing and not app.config.get("SECRET_KEY"):
        raise RuntimeError("SECRET_KEY must be set before starting SALES DASH.")
    if (
        app.config.get("APP_ENV") == "production"
        and not app.config.get("RATELIMIT_STORAGE_URI", "").startswith("redis://")
        and not app.config.get("RATELIMIT_STORAGE_URI", "").startswith("rediss://")
    ):
        raise RuntimeError("Production requires Redis-backed login rate limiting.")

    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    limiter.init_app(app)

    from .audit import audit_bp
    from .auth import auth_bp
    from .mfa import mfa_bp
    from .sales import sales_bp
    from .team import team_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(mfa_bp)
    app.register_blueprint(audit_bp)
    app.register_blueprint(sales_bp)
    app.register_blueprint(team_bp)
    register_commands(app)

    @app.errorhandler(CSRFError)
    def handle_csrf_error(_error):
        return jsonify({"error": "Your security token expired. Refresh and try again."}), 400

    @app.after_request
    def add_security_headers(response):
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; object-src 'none'; "
            "base-uri 'self'; frame-ancestors 'none'; form-action 'self'",
        )
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("X-Frame-Options", "DENY")
        if app.config.get("APP_ENV") == "production":
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response

    @app.get("/api/health")
    def health():
        return jsonify({"status": "ok", "service": "sales-dash-api"})

    @app.get("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    @app.get("/manifest.webmanifest")
    def pwa_manifest():
        response = send_from_directory(
            app.static_folder, "manifest.webmanifest", mimetype="application/manifest+json"
        )
        response.headers["Cache-Control"] = "no-cache"
        return response

    @app.get("/service-worker.js")
    def service_worker():
        response = send_from_directory(
            app.static_folder, "service-worker.js", mimetype="application/javascript"
        )
        response.headers["Cache-Control"] = "no-cache"
        response.headers["Service-Worker-Allowed"] = "/"
        return response

    return app
