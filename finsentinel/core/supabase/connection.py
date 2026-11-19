"""SQLAlchemy engine configuration for Supabase PostgreSQL."""

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from core.config import get_settings


def create_database_engine() -> Engine:
    """Create a SQLAlchemy engine for Supabase PostgreSQL."""
    settings = get_settings()

    return create_engine(
        settings.database_url,
        connect_args={
            "connect_timeout": 5,
            "options": "-c statement_timeout=30000",
        },
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        pool_timeout=30,
    )


engine = create_database_engine()
