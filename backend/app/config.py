import os
from datetime import timedelta

from dotenv import load_dotenv

load_dotenv()

APP_ENV = os.environ.get("APP_ENV", "development").lower()


class Config:
    """Shared application configuration."""

    APP_ENV = APP_ENV

    SECRET_KEY = os.environ.get("SECRET_KEY")
    # The web app uses a non-owner, non-superuser login. Admin URL is CLI/migration only.
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "APP_DATABASE_URL",
        "postgresql+psycopg://sales_dash_runtime:change-me@127.0.0.1:5432/sales_dash",
    )
    ADMIN_DATABASE_URL = os.environ.get("ADMIN_DATABASE_URL", os.environ.get("DATABASE_URL"))
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
    JSON_SORT_KEYS = False

    SESSION_COOKIE_NAME = "sales_dash_session"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = APP_ENV == "production"
    SESSION_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)
    SESSION_REFRESH_EACH_REQUEST = False

    RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")
    RATELIMIT_HEADERS_ENABLED = True

    # Google personal Gmail uses smtp.gmail.com with STARTTLS on port 587.
    # Credentials are supplied only through deployment environment variables.
    MAIL_SERVER = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
    MAIL_PORT = int(os.environ.get("MAIL_PORT", "587"))
    MAIL_USE_TLS = os.environ.get("MAIL_USE_TLS", "true").lower() == "true"
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD")
    MAIL_DEFAULT_SENDER = os.environ.get("MAIL_DEFAULT_SENDER", MAIL_USERNAME)
    MAIL_TIMEOUT = int(os.environ.get("MAIL_TIMEOUT", "10"))
    PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL")


class TestingConfig(Config):
    TESTING = True
    SECRET_KEY = "test-only-secret-do-not-use-in-production"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    WTF_CSRF_ENABLED = False
