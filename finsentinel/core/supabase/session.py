"""Database session management."""

from collections.abc import Generator

from sqlalchemy.orm import Session, sessionmaker

from core.supabase.connection import engine


SessionLocal = sessionmaker(
    bind=engine,
    class_=Session,
    autoflush=False,
    expire_on_commit=False,
)


def get_db() -> Generator[Session, None, None]:
    """Provide a database session and always close it."""
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()