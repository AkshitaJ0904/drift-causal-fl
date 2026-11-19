
"""Application configuration loaded from environment variables."""

import os
from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL

from detection.rule_based import RuleBasedDetectionConfig
from policy.detection_approval_policy import ApprovalAction


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

    # Detection thresholds (environment overrides)
    max_weight_l2_norm: float | None = None
    max_weight_abs_mean: float | None = None
    max_weight_std: float | None = None
    max_weight_zero_fraction: float | None = None
    min_weight_zero_fraction: float | None = None
    high_risk_action: ApprovalAction = "quarantined"

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


def get_detection_config(settings: Settings | None = None) -> RuleBasedDetectionConfig:
    """Build RuleBasedDetectionConfig from settings or environment.

    IMPORTANT SECURITY NOTE:
    Thresholds defined here are uncalibrated development defaults intended solely
    for experimental testing and pipeline validation. They must NOT be described
    or treated as production-safe security boundaries. In non-IID federated learning,
    arbitrary thresholds risk flagging legitimate client heterogeneity. Thresholds
    must be calibrated using representative clean updates and controlled attack distributions.

    Per project constraints, max_update_l2_norm is strictly disabled (None) until a
    trusted server-side reference model state dict is registered and available.
    """
    s = settings or get_settings()

    def _read_float(val: float | None, env_var: str) -> float | None:
        if val is not None:
            return float(val)
        raw = os.getenv(env_var)
        if raw is not None and raw.strip():
            return float(raw.strip())
        return None

    max_weight_l2_norm = _read_float(
        s.max_weight_l2_norm, "FINSENTINEL_MAX_WEIGHT_L2_NORM"
    )
    max_weight_abs_mean = _read_float(
        s.max_weight_abs_mean, "FINSENTINEL_MAX_WEIGHT_ABS_MEAN"
    )
    max_weight_std = _read_float(
        s.max_weight_std, "FINSENTINEL_MAX_WEIGHT_STD"
    )
    max_weight_zero_fraction = _read_float(
        s.max_weight_zero_fraction, "FINSENTINEL_MAX_WEIGHT_ZERO_FRACTION"
    )
    min_weight_zero_fraction = _read_float(
        s.min_weight_zero_fraction, "FINSENTINEL_MIN_WEIGHT_ZERO_FRACTION"
    )

    # Uncalibrated baseline defaults are allowed only for development/test.
    if all(
        v is None
        for v in (
            max_weight_l2_norm,
            max_weight_abs_mean,
            max_weight_std,
            max_weight_zero_fraction,
            min_weight_zero_fraction,
        )
    ) and s.environment.strip().lower() in {"development", "test"}:
        max_weight_l2_norm = 100.0
        max_weight_abs_mean = 10.0
        max_weight_std = 10.0
        max_weight_zero_fraction = 0.95

    if all(
        v is None
        for v in (
            max_weight_l2_norm,
            max_weight_abs_mean,
            max_weight_std,
            max_weight_zero_fraction,
            min_weight_zero_fraction,
        )
    ):
        raise ValueError(
            "Detection thresholds must be configured when the environment "
            "is not development or test."
        )

    return RuleBasedDetectionConfig(
        max_weight_l2_norm=max_weight_l2_norm,
        max_update_l2_norm=None,  # Disabled per constraint 2
        max_weight_abs_mean=max_weight_abs_mean,
        max_weight_std=max_weight_std,
        max_weight_zero_fraction=max_weight_zero_fraction,
        min_weight_zero_fraction=min_weight_zero_fraction,
    )


TRUST_MODE_CLIENT_CLAIMED = "client_claimed"
TRUST_MODE_COORDINATOR_VERIFIED = "coordinator_verified"
_VALID_TRUST_MODES = frozenset({TRUST_MODE_CLIENT_CLAIMED, TRUST_MODE_COORDINATOR_VERIFIED})


def get_sample_count_trust_mode() -> str:
    """Return the active sample-count trust mode.

    Reads ``FINSENTINEL_SAMPLE_COUNT_TRUST_MODE``.  Defaults to
    ``'client_claimed'`` when the variable is absent or empty.

    * ``'client_claimed'``: client-supplied counts are stored as-is with
      ``CLIENT_CLAIMED`` provenance.  A configured provider can upgrade counts
      to ``PROVIDER_VERIFIED`` but provider absence or failure is non-fatal.
    * ``'coordinator_verified'``: verified provenance is required at every
      stage.  Startup fails if no provider is configured; provider absence or
      failure blocks ingestion; ``CLIENT_CLAIMED`` records are rejected at
      approval and aggregation.

    Raises :class:`ValueError` for unrecognised values so deployments never
    silently default to a weaker trust guarantee.
    """
    raw = os.getenv("FINSENTINEL_SAMPLE_COUNT_TRUST_MODE")
    if raw is not None and raw.strip():
        val = raw.strip().lower()
    else:
        val = TRUST_MODE_CLIENT_CLAIMED
    if val not in _VALID_TRUST_MODES:
        raise ValueError(
            f"FINSENTINEL_SAMPLE_COUNT_TRUST_MODE must be one of "
            f"{sorted(_VALID_TRUST_MODES)!r}; got {val!r}."
        )
    return val


def get_high_risk_action(settings: Settings | None = None) -> ApprovalAction:
    """Return the validated action for high and critical anomaly assessments.

    FINSENTINEL_HIGH_RISK_ACTION is the documented environment-variable name and
    takes priority over the unprefixed HIGH_RISK_ACTION settings field.  Falls
    back to the settings field (populated from HIGH_RISK_ACTION) when the
    prefixed variable is absent or empty.  An invalid value always raises
    ValueError so detection policy never silently defaults to a weaker action.
    """
    raw_prefixed = os.getenv("FINSENTINEL_HIGH_RISK_ACTION")
    if raw_prefixed is not None and raw_prefixed.strip():
        raw: str = raw_prefixed.strip().lower()
    else:
        s = settings or get_settings()
        raw = s.high_risk_action
    if raw not in {"pending_approval", "quarantined"}:
        raise ValueError(
            "FINSENTINEL_HIGH_RISK_ACTION must be 'pending_approval' or 'quarantined'."
        )
    if raw == "pending_approval":
        return "pending_approval"
    return "quarantined"
