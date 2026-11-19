
"""Database-backed registry of trusted model schemas.

Schemas are persisted to the ``trusted_model_schemas`` table so that all
worker processes share the same tensor-spec definitions and they survive
process restarts.

``tensor_specs`` values are stored as JSON arrays ``[shape_list, dtype_str]``
and converted back to ``(tuple[int, ...], str)`` on read.

Fail-closed design: any database error during ``get_model_schema`` raises
``RegistryUnavailableError`` rather than passing through a degraded result.
"""

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError
from torch import Tensor

from audit.outbox import enqueue
from core.supabase.session import SessionLocal
from db.models.trusted_model_schema import TrustedModelSchema as TrustedModelSchemaRecord

logger = logging.getLogger(__name__)

_SAFE_ENVIRONMENTS: frozenset[str] = frozenset({"test", "development", "dev", "local"})


class RegistryUnavailableError(RuntimeError):
    """Raised when the registry DB is unreachable during a security-critical read."""


@dataclass(frozen=True)
class ModelSchema:
    model_version: str
    tensor_specs: dict[str, tuple[tuple[int, ...], str]]


class ModelSchemaNotFoundError(LookupError):
    """Raised when no trusted schema exists for a model version."""


def _encode_tensor_specs(specs: dict[str, tuple[tuple[int, ...], str]]) -> dict:
    return {name: [list(shape), dtype] for name, (shape, dtype) in specs.items()}


def _decode_tensor_specs(raw: dict) -> dict[str, tuple[tuple[int, ...], str]]:
    return {name: (tuple(spec[0]), spec[1]) for name, spec in raw.items()}


def register_model_schema(
    model_version: str,
    state_dict: Mapping[str, Tensor],
) -> None:
    """Persist a model schema derived from a trusted server-side model.

    If *model_version* already exists, the tensor specs are updated (UPSERT
    semantics).  Call this only from trusted provisioning code.
    """
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

    encoded = _encode_tensor_specs(tensor_specs)

    try:
        with SessionLocal() as db:
            existing = db.scalar(
                select(TrustedModelSchemaRecord).where(
                    TrustedModelSchemaRecord.model_version == model_version
                )
            )
            if existing is not None:
                existing.tensor_specs = encoded
                enqueue(
                    db,
                    event_id=None,
                    event_type="schema.registered",
                    severity="info",
                    description=(
                        f"Model schema {model_version!r} updated "
                        f"({len(tensor_specs)} tensor spec(s))"
                    ),
                    client_id=None,
                    update_id=None,
                )
                db.commit()
            else:
                record = TrustedModelSchemaRecord(
                    model_version=model_version,
                    tensor_specs=encoded,
                )
                db.add(record)
                enqueue(
                    db,
                    event_id=None,
                    event_type="schema.registered",
                    severity="info",
                    description=(
                        f"Model schema {model_version!r} registered "
                        f"({len(tensor_specs)} tensor spec(s))"
                    ),
                    client_id=None,
                    update_id=None,
                )
                db.commit()
    except SQLAlchemyError as exc:
        logger.exception("DB error registering model schema %r", model_version)
        raise RegistryUnavailableError(
            f"Registry unavailable while registering schema {model_version!r}"
        ) from exc


def get_model_schema(model_version: str) -> ModelSchema:
    """Retrieve a registered trusted schema.

    Raises ``ModelSchemaNotFoundError`` if no schema is registered for the
    given version.  Raises ``RegistryUnavailableError`` on any database
    failure (fail-closed: a DB outage must not be confused with "not found").
    """
    try:
        with SessionLocal() as db:
            record = db.scalar(
                select(TrustedModelSchemaRecord).where(
                    TrustedModelSchemaRecord.model_version == model_version
                )
            )
    except SQLAlchemyError as exc:
        logger.exception("DB error looking up model schema %r", model_version)
        raise RegistryUnavailableError(
            f"Registry unavailable while looking up schema {model_version!r}"
        ) from exc

    if record is None:
        raise ModelSchemaNotFoundError(
            f"No schema registered for model version {model_version!r}."
        )

    return ModelSchema(
        model_version=record.model_version,
        tensor_specs=_decode_tensor_specs(record.tensor_specs),
    )


def clear_model_schemas() -> None:
    """Delete all model schema records.  For tests and local development only.

    Raises ``RuntimeError`` if the ``ENVIRONMENT`` variable is not set to a
    recognised safe value to prevent accidental production truncation.
    """
    environment = os.environ.get("ENVIRONMENT", "").lower()
    if environment not in _SAFE_ENVIRONMENTS:
        raise RuntimeError(
            f"clear_model_schemas() refuses to run in ENVIRONMENT={environment!r}. "
            "Only 'test', 'development', 'dev', or 'local' environments are permitted."
        )
    try:
        with SessionLocal() as db:
            db.execute(delete(TrustedModelSchemaRecord))
            db.commit()
    except SQLAlchemyError as exc:
        logger.exception("DB error clearing model schemas")
        raise RegistryUnavailableError(
            "Registry unavailable while clearing schemas"
        ) from exc
