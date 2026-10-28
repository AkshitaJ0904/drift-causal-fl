
"""Check connectivity to the configured PostgreSQL database."""

from sqlalchemy import text

from core.supabase.connection import engine


def main() -> None:
    with engine.connect() as connection:
        result = connection.execute(
            text("SELECT current_database(), current_user, version()")
        )
        database, user, version = result.one()

        print("Database connection successful.")
        print(f"Database: {database}")
        print(f"Connected user: {user}")
        print(f"PostgreSQL version: {version.split(',')[0]}")


if __name__ == "__main__":
    main()
