import os


class Config:
    """Shared application configuration."""

    SECRET_KEY = os.environ.get("SECRET_KEY")
    JSON_SORT_KEYS = False


class TestingConfig(Config):
    TESTING = True
    SECRET_KEY = "test-only-secret-do-not-use-in-production"
