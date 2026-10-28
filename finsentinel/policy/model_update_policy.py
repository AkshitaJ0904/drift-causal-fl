
"""Deterministic zero-trust policies for federated-learning updates."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from ingestion.schemas import UpdateEnvelope


@dataclass(frozen=True)
class ModelUpdatePolicy:
    """Explicit rules governing which updates may be accepted."""

    allowed_model_versions: frozenset[str]
    allowed_round_numbers: frozenset[int]
    max_update_age_seconds: int = 900
    max_future_clock_skew_seconds: int = 60

    def __post_init__(self) -> None:
        if not self.allowed_model_versions:
            raise ValueError("At least one model version must be allowed.")

        if not self.allowed_round_numbers:
            raise ValueError("At least one training round must be allowed.")

        if any(round_number < 1 for round_number in self.allowed_round_numbers):
            raise ValueError("Training rounds must be positive.")

        if self.max_update_age_seconds < 0:
            raise ValueError("Maximum update age cannot be negative.")

        if self.max_future_clock_skew_seconds < 0:
            raise ValueError("Future clock skew cannot be negative.")


@dataclass(frozen=True)
class PolicyDecision:
    accepted: bool
    reason_code: str
    reason: str


def evaluate_update_policy(
    envelope: UpdateEnvelope,
    policy: ModelUpdatePolicy,
    *,
    now: datetime | None = None,
) -> PolicyDecision:
    """Evaluate model-version, round, and timestamp policies."""

    current_time = now or datetime.now(timezone.utc)

    if current_time.tzinfo is None or current_time.utcoffset() is None:
        raise ValueError("'now' must be timezone-aware.")

    current_time = current_time.astimezone(timezone.utc)
    created_at = envelope.created_at.astimezone(timezone.utc)

    if envelope.model_version not in policy.allowed_model_versions:
        return PolicyDecision(
            False,
            "model_version_not_allowed",
            "The model version is not allowed by the active policy.",
        )

    if envelope.round_number not in policy.allowed_round_numbers:
        return PolicyDecision(
            False,
            "training_round_not_allowed",
            "The training round is not open for update submissions.",
        )

    if created_at > current_time + timedelta(
        seconds=policy.max_future_clock_skew_seconds
    ):
        return PolicyDecision(
            False,
            "update_timestamp_in_future",
            "The update timestamp exceeds the permitted clock skew.",
        )

    if current_time - created_at > timedelta(
        seconds=policy.max_update_age_seconds
    ):
        return PolicyDecision(
            False,
            "update_too_old",
            "The update exceeds the permitted age.",
        )

    return PolicyDecision(
        True,
        "policy_accepted",
        "The update satisfies the active model-version, round, and time policies.",
    )
