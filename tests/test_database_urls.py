from app.config import normalize_database_url


def test_render_postgres_url_uses_installed_psycopg_driver():
    assert (
        normalize_database_url("postgres://user:pass@host:5432/app")
        == "postgresql+psycopg://user:pass@host:5432/app"
    )
    assert (
        normalize_database_url("postgresql://user:pass@host:5432/app")
        == "postgresql+psycopg://user:pass@host:5432/app"
    )


def test_driver_qualified_database_url_is_preserved():
    url = "postgresql+psycopg://user:pass@host:5432/app?sslmode=require"
    assert normalize_database_url(url) == url


def test_non_postgres_and_missing_database_urls_are_preserved():
    assert normalize_database_url("sqlite:///test.db") == "sqlite:///test.db"
    assert normalize_database_url(None) is None
