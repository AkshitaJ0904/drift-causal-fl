
"""Server-side model schema validation for federated-learning updates."""

from collections.abc import Mapping
from dataclasses import dataclass

from torch import Tensor

from features.update_validation import validate_state_dict


@dataclass(frozen=True)
class ModelSchemaResult:
    """Outcome of validating an update against the expected global model."""

    accepted: bool
    reason: str
    tensor_count: int
    total_bytes: int


def validate_model_schema(
    submitted_state_dict: Mapping[str, Tensor],
    expected_state_dict: Mapping[str, Tensor],
    *,
    max_total_bytes: int = 100_000_000,
) -> ModelSchemaResult:
    """Check submitted weights against the server's trusted model schema.

    The expected state dictionary must come from the server's trusted model,
    never from the incoming client payload.
    """
    result = validate_state_dict(
        submitted_state_dict,
        expected_state_dict=expected_state_dict,
        max_total_bytes=max_total_bytes,
    )

    return ModelSchemaResult(
        accepted=result.accepted,
        reason=result.reason,
        tensor_count=result.tensor_count,
        total_bytes=result.total_bytes,
    )


def validate_against_registered_schema(
    submitted_state_dict: Mapping[str, Tensor],
    *,
    model_version: str,
    max_total_bytes: int = 100_000_000,
) -> ModelSchemaResult:
    """Validate submitted tensors against the trusted registered schema."""
    from core.model_registry import (
        ModelSchemaNotFoundError,
        get_model_schema,
    )

    # Validate tensor types, shapes/basic properties, finiteness and size first.
    result = validate_state_dict(
        submitted_state_dict,
        max_total_bytes=max_total_bytes,
    )

    if not result.accepted:
        return ModelSchemaResult(
            accepted=False,
            reason=result.reason,
            tensor_count=result.tensor_count,
            total_bytes=result.total_bytes,
        )

    try:
        schema = get_model_schema(model_version)
    except ModelSchemaNotFoundError:
        return ModelSchemaResult(
            accepted=False,
            reason=f"No trusted schema registered for model version {model_version!r}.",
            tensor_count=result.tensor_count,
            total_bytes=result.total_bytes,
        )

    submitted_names = set(submitted_state_dict)
    expected_names = set(schema.tensor_specs)

    if submitted_names != expected_names:
        return ModelSchemaResult(
            accepted=False,
            reason="Tensor names do not match the registered model schema.",
            tensor_count=result.tensor_count,
            total_bytes=result.total_bytes,
        )

    for name, tensor in submitted_state_dict.items():
        expected_shape, expected_dtype = schema.tensor_specs[name]

        if tuple(tensor.shape) != expected_shape:
            return ModelSchemaResult(
                accepted=False,
                reason=f"Tensor {name!r} has a shape mismatch.",
                tensor_count=result.tensor_count,
                total_bytes=result.total_bytes,
            )

        if str(tensor.dtype) != expected_dtype:
            return ModelSchemaResult(
                accepted=False,
                reason=f"Tensor {name!r} has a dtype mismatch.",
                tensor_count=result.tensor_count,
                total_bytes=result.total_bytes,
            )

    return ModelSchemaResult(
        accepted=True,
        reason="Update matches the registered model schema.",
        tensor_count=result.tensor_count,
        total_bytes=result.total_bytes,
    )
