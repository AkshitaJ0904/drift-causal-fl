
"""HTTP endpoint for receiving federated-learning updates."""

import base64
import binascii
import os

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from core.replay_protection import ReplayProtectionError
from ingestion.payload import PayloadIntegrityError
from ingestion.schemas import UpdateEnvelope
from ingestion.serialization import SerializationError
from ingestion.service import (
    ApprovalRegistrationError,
    ModelSchemaValidationError,
    UpdateAuthenticationError,
    UpdatePolicyRejectedError,
    validate_incoming_update,
)
from policy.model_update_policy import ModelUpdatePolicy

router = APIRouter(prefix="/updates", tags=["ingestion"])

MAX_REQUEST_SIZE_BYTES = 10_000_000


class UpdateSubmission(BaseModel):
    """JSON request containing update metadata and a Base64 payload."""

    model_config = ConfigDict(extra="forbid")

    envelope: UpdateEnvelope
    payload_base64: str = Field(min_length=1)


def get_active_model_update_policy() -> ModelUpdatePolicy:
    """Load the trusted update policy configured by the server operator."""

    raw_versions = os.getenv("FINSENTINEL_ALLOWED_MODEL_VERSIONS", "")
    raw_rounds = os.getenv("FINSENTINEL_ALLOWED_ROUNDS", "")

    versions = frozenset(
        value.strip()
        for value in raw_versions.split(",")
        if value.strip()
    )

    try:
        rounds = frozenset(
            int(value.strip())
            for value in raw_rounds.split(",")
            if value.strip()
        )

        max_age = int(
            os.getenv("FINSENTINEL_MAX_UPDATE_AGE_SECONDS", "900")
        )
        max_clock_skew = int(
            os.getenv("FINSENTINEL_MAX_FUTURE_CLOCK_SKEW_SECONDS", "60")
        )

        return ModelUpdatePolicy(
            allowed_model_versions=versions,
            allowed_round_numbers=rounds,
            max_update_age_seconds=max_age,
            max_future_clock_skew_seconds=max_clock_skew,
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=503,
            detail="Active update policy configuration is invalid.",
        ) from exc


@router.post("")
async def submit_update(
    submission: UpdateSubmission,
    request: Request,
) -> dict[str, str | int]:
    """Validate an update and register it for approval."""

    # 1. Check the declared HTTP request size.
    content_length = request.headers.get("content-length")

    if content_length is not None:
        try:
            declared_size = int(content_length)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail="Invalid Content-Length header",
            ) from exc

        if declared_size < 0:
            raise HTTPException(
                status_code=400,
                detail="Invalid Content-Length header",
            )

        if declared_size > MAX_REQUEST_SIZE_BYTES:
            raise HTTPException(
                status_code=413,
                detail="Request exceeds the maximum allowed size",
            )

    # 2. Decode the Base64 payload.
    try:
        payload = base64.b64decode(
            submission.payload_base64,
            validate=True,
        )
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail="Payload must be valid Base64",
        ) from exc

    if len(payload) > MAX_REQUEST_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail="Decoded payload exceeds the endpoint size limit",
        )

    # 3. Load the trusted server-side policy.
    policy = get_active_model_update_policy()

    # 4. Validate the update and register it as pending approval.
    try:
        result = validate_incoming_update(
            payload,
            submission.envelope,
            policy=policy,
        )
    except PayloadIntegrityError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc
    except UpdateAuthenticationError as exc:
        raise HTTPException(
            status_code=401,
            detail=str(exc),
        ) from exc
    except ReplayProtectionError as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc
    except SerializationError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid serialized model update: {exc}",
        ) from exc
    except ModelSchemaValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Model schema validation failed: {exc}",
        ) from exc
    except UpdatePolicyRejectedError as exc:
        raise HTTPException(
            status_code=403,
            detail={
                "code": exc.reason_code,
                "message": str(exc),
            },
        ) from exc
    except ApprovalRegistrationError as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc

    # 5. Return metadata only; never expose reconstructed model weights.
    result.pop("state_dict", None)
    result.pop("tensor_names", None)

    return result
