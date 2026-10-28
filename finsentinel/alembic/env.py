
"""Alembic environment configuration for FinSentinel."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool

from core.config import get_settings
from core.supabase.base import Base
from core.supabase.connection import engine
from db.models import AuditEvent,UpdateApproval

# Alembic configuration
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Register SQLAlchemy metadata for autogenerate support.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Generate SQL migrations without opening a database connection."""
    settings = get_settings()

    context.configure(
        url=settings.database_url.render_as_string(hide_password=False),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations using the configured Supabase engine."""
    with engine.connect() as connection:
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
