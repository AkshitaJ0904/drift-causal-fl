
"""Security tests for approval-gated FedAvg aggregation."""

import hashlib

import pytest
import torch

from aggregation.service import (
    AggregationRejectedError,
    ApprovedUpdatePayload,
    aggregate_approved_updates,
)
from core.supabase.session import SessionLocal
from enforcement.approval_service import (
    approve_update,
    clear_approval_registry,
    register_validated_update,
)
from ingestion.serialization import serialize_state_dict


@pytest.fixture(autouse=True)
def reset_approval_registry():
    clear_approval_registry()
    yield
    clear_approval_registry()


def make_payload(value: float) -> bytes:
    return serialize_state_dict(
        {
            "layer.weight": torch.tensor([[value, value]], dtype=torch.float32),
            "layer.bias": torch.tensor([value], dtype=torch.float32),
        }
    )


def register_and_approve(
    *,
    client_id: str,
    update_id: str,
    payload: bytes,
    model_version: str = "cnn-v1",
    round_number: int = 1,
) -> None:
    register_validated_update(
        client_id=client_id,
        update_id=update_id,
        model_version=model_version,
        round_number=round_number,
        payload_sha256=hashlib.sha256(payload).hexdigest(),
    )
    approve_update(
        client_id=client_id,
        update_id=update_id,
        reason="Approved for aggregation test.",
    )


def make_update(
    *,
    client_id: str,
    update_id: str,
    payload: bytes,
    sample_count: int = 1,
    model_version: str = "cnn-v1",
    round_number: int = 1,
) -> ApprovedUpdatePayload:
    return ApprovedUpdatePayload(
        client_id=client_id,
        update_id=update_id,
        model_version=model_version,
        round_number=round_number,
        payload=payload,
        sample_count=sample_count,
    )


def expected_model():
    return {
        "layer.weight": torch.zeros((1, 2), dtype=torch.float32),
        "layer.bias": torch.zeros(1, dtype=torch.float32),
    }


def test_unapproved_update_cannot_be_aggregated():
    payload = make_payload(1.0)

    update = make_update(
        client_id="client-001",
        update_id="update-001",
        payload=payload,
    )

    with pytest.raises(AggregationRejectedError, match="not approved"):
        aggregate_approved_updates(
            [update],
            expected_state_dict=expected_model(),
            model_version="cnn-v1",
            round_number=1,
        )


def test_approved_payload_is_aggregated():
    payload = make_payload(2.0)
    register_and_approve(
        client_id="client-001",
        update_id="update-001",
        payload=payload,
    )

    result = aggregate_approved_updates(
        [
            make_update(
                client_id="client-001",
                update_id="update-001",
                payload=payload,
                sample_count=3,
            )
        ],
        expected_state_dict=expected_model(),
        model_version="cnn-v1",
        round_number=1,
    )

    assert torch.equal(
        result["layer.weight"],
        torch.tensor([[2.0, 2.0]]),
    )
    assert torch.equal(result["layer.bias"], torch.tensor([2.0]))


def test_modified_payload_is_rejected():
    original = make_payload(2.0)
    register_and_approve(
        client_id="client-001",
        update_id="update-001",
        payload=original,
    )

    tampered = original + b"tampered"
    update = make_update(
        client_id="client-001",
        update_id="update-001",
        payload=tampered,
    )

    with pytest.raises(AggregationRejectedError, match="not approved"):
        aggregate_approved_updates(
            [update],
            expected_state_dict=expected_model(),
            model_version="cnn-v1",
            round_number=1,
        )


def test_wrong_model_version_is_rejected():
    payload = make_payload(1.0)
    register_and_approve(
        client_id="client-001",
        update_id="update-001",
        payload=payload,
    )

    with pytest.raises(AggregationRejectedError, match="model version"):
        aggregate_approved_updates(
            [
                make_update(
                    client_id="client-001",
                    update_id="update-001",
                    payload=payload,
                    model_version="cnn-v2",
                )
            ],
            expected_state_dict=expected_model(),
            model_version="cnn-v1",
            round_number=1,
        )


def test_wrong_round_is_rejected():
    payload = make_payload(1.0)
    register_and_approve(
        client_id="client-001",
        update_id="update-001",
        payload=payload,
    )

    with pytest.raises(AggregationRejectedError, match="round"):
        aggregate_approved_updates(
            [
                make_update(
                    client_id="client-001",
                    update_id="update-001",
                    payload=payload,
                    round_number=2,
                )
            ],
            expected_state_dict=expected_model(),
            model_version="cnn-v1",
            round_number=1,
        )


def test_rejected_update_cannot_be_aggregated():
    payload = make_payload(1.0)
    register_validated_update(
        client_id="client-001",
        update_id="update-001",
        model_version="cnn-v1",
        round_number=1,
        payload_sha256=hashlib.sha256(payload).hexdigest(),
    )

    from enforcement.approval_service import reject_update

    reject_update(
        client_id="client-001",
        update_id="update-001",
        reason="Security test rejection.",
    )

    with pytest.raises(AggregationRejectedError, match="not approved"):
        aggregate_approved_updates(
            [
                make_update(
                    client_id="client-001",
                    update_id="update-001",
                    payload=payload,
                )
            ],
            expected_state_dict=expected_model(),
            model_version="cnn-v1",
            round_number=1,
        )


def test_weighted_fedavg_uses_sample_counts():
    payload_a = make_payload(1.0)
    payload_b = make_payload(3.0)

    register_and_approve(
        client_id="client-001",
        update_id="update-001",
        payload=payload_a,
    )
    register_and_approve(
        client_id="client-002",
        update_id="update-002",
        payload=payload_b,
    )

    result = aggregate_approved_updates(
        [
            make_update(
                client_id="client-001",
                update_id="update-001",
                payload=payload_a,
                sample_count=1,
            ),
            make_update(
                client_id="client-002",
                update_id="update-002",
                payload=payload_b,
                sample_count=3,
            ),
        ],
        expected_state_dict=expected_model(),
        model_version="cnn-v1",
        round_number=1,
    )

    # (1 * 1.0 + 3 * 3.0) / (1 + 3) = 2.5
    assert torch.allclose(
        result["layer.weight"],
        torch.tensor([[2.5, 2.5]]),
    )
    assert torch.allclose(result["layer.bias"], torch.tensor([2.5]))


def test_duplicate_update_is_rejected():
    payload = make_payload(1.0)
    register_and_approve(
        client_id="client-001",
        update_id="update-001",
        payload=payload,
    )
    update = make_update(
        client_id="client-001",
        update_id="update-001",
        payload=payload,
    )

    with pytest.raises(AggregationRejectedError, match="Duplicate update"):
        aggregate_approved_updates(
            [update, update],
            expected_state_dict=expected_model(),
            model_version="cnn-v1",
            round_number=1,
        )


def test_empty_update_list_is_rejected():
    with pytest.raises(AggregationRejectedError, match="At least one"):
        aggregate_approved_updates(
            [],
            expected_state_dict=expected_model(),
            model_version="cnn-v1",
            round_number=1,
        )


def test_nonpositive_sample_count_is_rejected():
    payload = make_payload(1.0)
    register_and_approve(
        client_id="client-001",
        update_id="update-001",
        payload=payload,
    )

    with pytest.raises(AggregationRejectedError, match="sample_count"):
        aggregate_approved_updates(
            [
                make_update(
                    client_id="client-001",
                    update_id="update-001",
                    payload=payload,
                    sample_count=0,
                )
            ],
            expected_state_dict=expected_model(),
            model_version="cnn-v1",
            round_number=1,
        )
