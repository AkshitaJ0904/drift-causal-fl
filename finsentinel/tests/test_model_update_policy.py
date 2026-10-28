
from datetime import datetime, timedelta, timezone

from ingestion.schemas import UpdateEnvelope
from policy.model_update_policy import (
    ModelUpdatePolicy,
    evaluate_update_policy,
)


def make_envelope(
    *,
    model_version="cnn-v1",
    round_number=5,
    created_at=None,
):
    return UpdateEnvelope(
        update_id="update-policy-001",
        client_id="client-001",
        model_version=model_version,
        round_number=round_number,
        payload_sha256="a" * 64,
        payload_size_bytes=100,
        created_at=created_at or datetime(
            2026, 10, 22, 12, 0, tzinfo=timezone.utc
        ),
        signature="test-signature",
        signing_key_id="key-001",
    )


def make_policy():
    return ModelUpdatePolicy(
        allowed_model_versions=frozenset({"cnn-v1"}),
        allowed_round_numbers=frozenset({5}),
    )


def test_accepts_update_matching_active_policy():
    now = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)

    decision = evaluate_update_policy(
        make_envelope(created_at=now),
        make_policy(),
        now=now,
    )

    assert decision.accepted is True
    assert decision.reason_code == "policy_accepted"


def test_rejects_unapproved_model_version():
    now = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)

    decision = evaluate_update_policy(
        make_envelope(model_version="cnn-v0", created_at=now),
        make_policy(),
        now=now,
    )

    assert decision.accepted is False
    assert decision.reason_code == "model_version_not_allowed"


def test_rejects_closed_training_round():
    now = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)

    decision = evaluate_update_policy(
        make_envelope(round_number=4, created_at=now),
        make_policy(),
        now=now,
    )

    assert decision.accepted is False
    assert decision.reason_code == "training_round_not_allowed"


def test_rejects_stale_update():
    now = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)
    created_at = now - timedelta(minutes=16)

    decision = evaluate_update_policy(
        make_envelope(created_at=created_at),
        make_policy(),
        now=now,
    )

    assert decision.accepted is False
    assert decision.reason_code == "update_too_old"


def test_rejects_timestamp_too_far_in_future():
    now = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)
    created_at = now + timedelta(minutes=2)

    decision = evaluate_update_policy(
        make_envelope(created_at=created_at),
        make_policy(),
        now=now,
    )

    assert decision.accepted is False
    assert decision.reason_code == "update_timestamp_in_future"
