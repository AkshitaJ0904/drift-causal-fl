
"""Registry of trusted server-side model schemas."""

from collections.abc import Mapping
from dataclasses import dataclass

from torch import Tensor


@dataclass(frozen=True)
class ModelSchema:
    model_version: str
    tensor_specs: dict[str, tuple[tuple[int, ...], str]]


class ModelSchemaNotFoundError(LookupError):
    """Raised when no trusted schema exists for a model version."""


_model_schemas: dict[str, ModelSchema] = {}


def register_model_schema(
    model_version: str,
    state_dict: Mapping[str, Tensor],
) -> None:
    """Register a schema from a trusted server-side model."""
    if not model_version or not model_version.strip():
        raise ValueError("model_version must not be empty.")

    if not state_dict:
        raise ValueError("Trusted model state_dict must not be empty.")

    tensor_specs: dict[str, tuple[tuple[int, ...], str]] = {}

    for name, tensor in state_dict.items():
        if not isinstance(name, str) or not name:
            raise ValueError("Tensor names must be non-empty strings.")

        if not isinstance(tensor, Tensor):
            raise ValueError(f"Trusted model entry {name!r} is not a tensor.")

        tensor_specs[name] = (tuple(tensor.shape), str(tensor.dtype))

    _model_schemas[model_version] = ModelSchema(
        model_version=model_version,
        tensor_specs=tensor_specs,
    )


def get_model_schema(model_version: str) -> ModelSchema:
    """Retrieve a registered trusted schema."""
    try:
        return _model_schemas[model_version]
    except KeyError as exc:
        raise ModelSchemaNotFoundError(
            f"No schema registered for model version {model_version!r}."
        ) from exc


def clear_model_schemas() -> None:
    """Clear registered schemas; useful for isolated tests."""
    _model_schemas.clear()
