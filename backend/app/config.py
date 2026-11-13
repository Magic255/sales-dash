import os


class Config:
    """Shared application configuration."""

    SECRET_KEY = os.environ.get("SECRET_KEY")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL",
        "postgresql+psycopg://sales_dash:sales_dash_dev@127.0.0.1:5432/sales_dash",
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
    JSON_SORT_KEYS = False


class TestingConfig(Config):
    TESTING = True
    SECRET_KEY = "test-only-secret-do-not-use-in-production"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
