
"""Application configuration loaded from environment variables."""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    """Validated application and database settings."""

    app_name: str = "FinSentinel"
    environment: str = "development"
    api_prefix: str = "/api/v1"
    log_level: str = "INFO"

    # Supabase PostgreSQL connection settings
    db_user: str = ""
    db_password: SecretStr = SecretStr("")
    db_host: str = ""
    db_port: int = 5432
    db_name: str = "postgres"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    @property
    def database_url(self) -> URL:
        """Build the SQLAlchemy database URL safely."""
        password = self.db_password.get_secret_value()

        if not all((self.db_user, password, self.db_host, self.db_name)):
            raise ValueError(
                "Database configuration is incomplete. "
                "Check DB_USER, DB_PASSWORD, DB_HOST, and DB_NAME in .env."
            )

        return URL.create(
            drivername="postgresql+psycopg",
            username=self.db_user,
            password=password,
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
            query={"sslmode": "require"},
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()
