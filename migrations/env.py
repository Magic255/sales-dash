import os
from logging.config import fileConfig

from alembic import context
from flask import current_app
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from backend.app.config import normalize_database_url

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

db = current_app.extensions["migrate"].db
target_metadata = db.metadata
_admin_engine = None


def get_engine():
    """Use a dedicated admin connection for migrations, never the web runtime role."""
    global _admin_engine
    admin_url = normalize_database_url(os.environ.get("ADMIN_DATABASE_URL"))
    if admin_url:
        _admin_engine = create_engine(admin_url, poolclass=NullPool, pool_pre_ping=True)
        return _admin_engine
    return db.engine


def run_migrations_offline():
    url = get_engine().url.render_as_string(hide_password=False)
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    with get_engine().connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
    if _admin_engine is not None:
        _admin_engine.dispose()
