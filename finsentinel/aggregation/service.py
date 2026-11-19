
"""Approval-gated weighted FedAvg aggregation."""

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass

import torch
from torch import Tensor

from core.config import TRUST_MODE_COORDINATOR_VERIFIED, get_sample_count_trust_mode
from enforcement.approval_service import is_approved
from features.model_schema import validate_model_schema
from ingestion.serialization import deserialize_state_dict


class AggregationRejectedError(ValueError):
    """Raised when an update cannot safely enter aggregation."""


@dataclass(frozen=True)
class ApprovedUpdatePayload:
    """Original payload and identity for one proposed aggregation input."""

    client_id: str
    update_id: str
    model_version: str
    round_number: int
    payload: bytes
    sample_count: int
    sample_count_provenance: str | None = None


def aggregate_approved_updates(
    updates: list[ApprovedUpdatePayload],
    *,
    expected_state_dict: Mapping[str, Tensor],
    model_version: str,
    round_number: int,
    max_total_bytes: int = 10_000_000,
    require_verified_provenance: bool = False,
) -> dict[str, Tensor]:
    """Aggregate only payloads whose exact bytes have been approved.

    The expected state dictionary must come from the trusted server model.
    This function accepts original serialized payload bytes so it can verify
    the exact digest recorded during ingestion.
    """
    trust_mode = get_sample_count_trust_mode()
    effective_require_verified = require_verified_provenance or (
        trust_mode == TRUST_MODE_COORDINATOR_VERIFIED
    )

    if not updates:
        raise AggregationRejectedError(
            "At least one approved update is required."
        )

    if not model_version.strip():
        raise AggregationRejectedError("model_version is required.")

    if round_number < 1:
        raise AggregationRejectedError("round_number must be positive.")

    if max_total_bytes < 1:
        raise AggregationRejectedError("max_total_bytes must be positive.")

    seen_updates: set[tuple[str, str]] = set()
    validated_updates: list[tuple[dict[str, Tensor], int]] = []

    for item in updates:
        identity = (item.client_id, item.update_id)

        if identity in seen_updates:
            raise AggregationRejectedError(
                "Duplicate update included in aggregation."
            )
        seen_updates.add(identity)

        if not item.client_id.strip() or not item.update_id.strip():
            raise AggregationRejectedError(
                "Client and update identifiers are required."
            )

        if item.model_version != model_version:
            raise AggregationRejectedError(
                "Update model version does not match the aggregation model."
            )

        if item.round_number != round_number:
            raise AggregationRejectedError(
                "Update round does not match the aggregation round."
            )

        if (
            isinstance(item.sample_count, bool)
            or not isinstance(item.sample_count, int)
            or item.sample_count <= 0
        ):
            raise AggregationRejectedError(
                "sample_count must be a positive integer."
            )

        if not isinstance(item.payload, bytes) or not item.payload:
            raise AggregationRejectedError(
                "A non-empty serialized payload is required."
            )

        if len(item.payload) > max_total_bytes:
            raise AggregationRejectedError(
                "Serialized update exceeds the configured payload limit."
            )

        actual_digest = hashlib.sha256(item.payload).hexdigest()

        if not is_approved(
            client_id=item.client_id,
            update_id=item.update_id,
            model_version=item.model_version,
            round_number=item.round_number,
            payload_sha256=actual_digest,
            sample_count=item.sample_count,
            require_verified_provenance=effective_require_verified,
        ):
            raise AggregationRejectedError(
                "Update is not approved for this exact payload, model, and round."
            )

        try:
            state_dict = deserialize_state_dict(
                item.payload,
                max_total_bytes=max_total_bytes,
            )
        except (ValueError, TypeError) as exc:
            raise AggregationRejectedError(
                "Approved payload could not be safely deserialized."
            ) from exc

        schema_result = validate_model_schema(
            state_dict,
            expected_state_dict=expected_state_dict,
            max_total_bytes=max_total_bytes,
        )

        if not schema_result.accepted:
            raise AggregationRejectedError(
                f"Update failed trusted model validation: {schema_result.reason}"
            )

        validated_updates.append((state_dict, item.sample_count))

    total_samples = sum(count for _, count in validated_updates)

    if total_samples <= 0:
        raise AggregationRejectedError(
            "Total sample count must be positive."
        )

    aggregated: dict[str, Tensor] = {}

    for name, server_tensor in expected_state_dict.items():
        if server_tensor.is_floating_point():
            accumulator = torch.zeros_like(
                server_tensor,
                dtype=torch.float64,
                device="cpu",
            )

            for state_dict, sample_count in validated_updates:
                tensor = state_dict[name].detach().to(
                    device="cpu",
                    dtype=torch.float64,
                )
                accumulator.add_(tensor, alpha=sample_count / total_samples)

            result = accumulator.to(dtype=server_tensor.dtype)

            if not torch.isfinite(result).all().item():
                raise AggregationRejectedError(
                    f"Aggregation produced non-finite values for {name!r}."
                )

            aggregated[name] = result
        else:
            # Integer buffers must match the server's trusted reference.
            # Comparing clients only against each other (not the server) would
            # allow a coordinated group to override the server value by all
            # agreeing on a forgery.
            server_value = server_tensor.detach().cpu()

            for state_dict, _ in validated_updates:
                candidate = state_dict[name].detach().cpu()

                if not torch.equal(server_value, candidate):
                    raise AggregationRejectedError(
                        f"Non-floating tensor {name!r} differs from server reference."
                    )

            aggregated[name] = server_value.clone()

    return aggregated
