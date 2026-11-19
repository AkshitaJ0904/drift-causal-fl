
"""HTTP endpoint for operator-triggered aggregation of approved FL updates.

This endpoint is the production integration boundary between the approval
pipeline and the FedAvg aggregation service.  A real federated-learning
coordinator would call this endpoint after operators have approved updates.
No live coordinator exists in this repository; this endpoint documents the
handoff contract without fabricating one.

Authentication: requires FINSENTINEL_OPERATOR_TOKEN bearer token.

The caller supplies:
  - The server's current trusted reference model (serialized NPZ), used for
    schema validation and as the aggregation baseline type specification.
  - The list of approved update payloads (serialized NPZ, Base64-encoded)
    with their identities and sample counts.

The service verifies database approval for each exact payload digest before
aggregation proceeds.  Unapproved, mismatched, or quarantined updates are
rejected.
"""

import base64
import binascii
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from aggregation.service import (
    AggregationRejectedError,
    ApprovedUpdatePayload,
    aggregate_approved_updates,
)
from api._auth import require_operator_auth
from ingestion.serialization import (
    SerializationError,
    deserialize_state_dict,
    serialize_state_dict,
)

router = APIRouter(prefix="/aggregation", tags=["aggregation"])

_MAX_AGGREGATION_BYTES = 10_000_000


class AggregationUpdateInput(BaseModel):
    """One approved client update submitted for aggregation."""

    model_config = ConfigDict(extra="forbid")

    client_id: str = Field(min_length=1)
    update_id: str = Field(min_length=1)
    model_version: str = Field(min_length=1)
    round_number: int = Field(ge=1, strict=True)
    sample_count: int = Field(gt=0, strict=True)
    payload_base64: str = Field(min_length=1)


class AggregationRunRequest(BaseModel):
    """Request body for one aggregation round.

    reference_payload_base64: The server operator's current trusted global
      model, serialized as NPZ.  Its tensors define the expected schema
      and are used for schema validation of each client update.
      This must come from the server's trusted model, never from a client.
    """

    model_config = ConfigDict(extra="forbid")

    model_version: str = Field(min_length=1)
    round_number: int = Field(ge=1, strict=True)
    updates: list[AggregationUpdateInput] = Field(min_length=1)
    reference_payload_base64: str = Field(min_length=1)


@router.post("/run")
def run_aggregation(
    body: AggregationRunRequest,
    request: Request,
) -> dict[str, Any]:
    """Aggregate approved updates for one federated-learning round.

    Only updates whose exact payload bytes have been approved in the
    database can enter aggregation.  Use the approval API first.

    Returns the aggregated model serialized as NPZ (Base64-encoded).
    """
    require_operator_auth(request)

    # Decode and deserialize the server's trusted reference model.
    try:
        reference_bytes = base64.b64decode(
            body.reference_payload_base64, validate=True
        )
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail="reference_payload_base64 is not valid Base64.",
        ) from exc

    try:
        reference_state_dict = deserialize_state_dict(
            reference_bytes,
            max_total_bytes=_MAX_AGGREGATION_BYTES,
        )
    except SerializationError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Reference model could not be deserialized: {exc}",
        ) from exc

    # Decode client update payloads.
    update_payloads: list[ApprovedUpdatePayload] = []
    for item in body.updates:
        try:
            payload_bytes = base64.b64decode(item.payload_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"payload_base64 for update {item.update_id!r} "
                    "is not valid Base64."
                ),
            ) from exc
        update_payloads.append(
            ApprovedUpdatePayload(
                client_id=item.client_id,
                update_id=item.update_id,
                model_version=item.model_version,
                round_number=item.round_number,
                payload=payload_bytes,
                sample_count=item.sample_count,
            )
        )

    # Run approval-gated weighted FedAvg.
    try:
        aggregated = aggregate_approved_updates(
            update_payloads,
            expected_state_dict=reference_state_dict,
            model_version=body.model_version,
            round_number=body.round_number,
            max_total_bytes=_MAX_AGGREGATION_BYTES,
        )
    except AggregationRejectedError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Serialize the aggregated result.
    try:
        aggregated_bytes = serialize_state_dict(
            aggregated,
            max_total_bytes=_MAX_AGGREGATION_BYTES,
        )
    except SerializationError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Aggregated model could not be serialized: {exc}",
        ) from exc

    return {
        "model_version": body.model_version,
        "round_number": body.round_number,
        "update_count": len(update_payloads),
        "total_samples": sum(u.sample_count for u in update_payloads),
        "tensor_count": len(aggregated),
        "tensor_names": list(aggregated.keys()),
        "aggregated_payload_base64": base64.b64encode(aggregated_bytes).decode("ascii"),
    }
