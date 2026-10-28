
"""Application service for validating incoming federated-learning updates."""

import logging

from audit.service import record_audit_event
from core.crypto import verify_envelope_signature
from core.key_registry import get_trusted_key
from core.replay_protection import ReplayProtectionError, reserve_update
from enforcement.approval_service import (
    ApprovalError,
    register_validated_update,
)
from features.model_schema import validate_against_registered_schema
from ingestion.payload import PayloadIntegrityError, verify_payload
from ingestion.schemas import UpdateEnvelope
from ingestion.serialization import SerializationError, deserialize_state_dict
from policy.model_update_policy import (
    ModelUpdatePolicy,
    evaluate_update_policy,
)

logger = logging.getLogger(__name__)

MAX_UPDATE_BYTES = 10_000_000


class UpdateAuthenticationError(ValueError):
    """Raised when an update cannot be authenticated."""


class ModelSchemaValidationError(ValueError):
    """Raised when an update does not match a trusted model schema."""


class UpdatePolicyRejectedError(ValueError):
    """Raised when an update violates the active security policy."""

    def __init__(self, reason_code: str, message: str):
        super().__init__(message)
        self.reason_code = reason_code


class ApprovalRegistrationError(RuntimeError):
    """Raised when a validated update cannot enter the approval queue."""


def _audit_safely(
    *,
    event_type: str,
    severity: str,
    description: str,
    client_id: str | None = None,
    update_id: str | None = None,
) -> None:
    """Record an audit event without masking the original result."""
    try:
        record_audit_event(
            event_type=event_type,
            severity=severity,
            description=description,
            client_id=client_id,
            update_id=update_id,
        )
    except Exception:
        logger.exception(
            "Audit persistence failed for event_type=%s",
            event_type,
        )


def validate_incoming_update(
    payload: bytes,
    envelope: UpdateEnvelope,
    *,
    policy: ModelUpdatePolicy,
) -> dict[str, object]:
    """Validate an update and register its exact payload for approval.

    Passing ingestion validation does not authorize aggregation.
    """
    try:
        verified_sha256 = verify_payload(payload, envelope)
    except PayloadIntegrityError:
        _audit_safely(
            event_type="security.payload_integrity_failed",
            severity="high",
            description="Incoming payload failed integrity verification.",
            client_id=envelope.client_id,
            update_id=envelope.update_id,
        )
        raise

    trusted_key = get_trusted_key(envelope.signing_key_id)

    if trusted_key is None:
        _audit_safely(
            event_type="security.unknown_signing_key",
            severity="high",
            description="Update references an unregistered signing key.",
            client_id=envelope.client_id,
            update_id=envelope.update_id,
        )
        raise UpdateAuthenticationError("Unknown signing key")

    if trusted_key.client_id != envelope.client_id:
        _audit_safely(
            event_type="security.client_key_mismatch",
            severity="high",
            description="Signing key is not authorized for the claimed client.",
            client_id=envelope.client_id,
            update_id=envelope.update_id,
        )
        raise UpdateAuthenticationError(
            "Signing key is not authorized for this client"
        )

    if not verify_envelope_signature(envelope, trusted_key.public_key):
        _audit_safely(
            event_type="security.signature_verification_failed",
            severity="high",
            description="Update envelope signature verification failed.",
            client_id=envelope.client_id,
            update_id=envelope.update_id,
        )
        raise UpdateAuthenticationError("Invalid update signature")

    try:
        state_dict = deserialize_state_dict(
            payload,
            max_total_bytes=MAX_UPDATE_BYTES,
        )
    except SerializationError:
        _audit_safely(
            event_type="security.serialization_failed",
            severity="high",
            description=(
                "Authenticated payload failed safe model-weight deserialization."
            ),
            client_id=envelope.client_id,
            update_id=envelope.update_id,
        )
        raise

    schema_result = validate_against_registered_schema(
        state_dict,
        model_version=envelope.model_version,
        max_total_bytes=MAX_UPDATE_BYTES,
    )

    if not schema_result.accepted:
        _audit_safely(
            event_type="security.model_schema_rejected",
            severity="high",
            description=schema_result.reason,
            client_id=envelope.client_id,
            update_id=envelope.update_id,
        )
        raise ModelSchemaValidationError(schema_result.reason)

    decision = evaluate_update_policy(envelope, policy)

    if not decision.accepted:
        _audit_safely(
            event_type=f"security.policy_rejected.{decision.reason_code}",
            severity="high",
            description=decision.reason,
            client_id=envelope.client_id,
            update_id=envelope.update_id,
        )
        raise UpdatePolicyRejectedError(
            decision.reason_code,
            decision.reason,
        )

    try:
        reserve_update(envelope)
    except ReplayProtectionError:
        _audit_safely(
            event_type="security.replay_detected",
            severity="high",
            description="Update rejected by replay protection.",
            client_id=envelope.client_id,
            update_id=envelope.update_id,
        )
        raise

    try:
        approval_record = register_validated_update(
            update_id=envelope.update_id,
            client_id=envelope.client_id,
            model_version=envelope.model_version,
            round_number=envelope.round_number,
            payload_sha256=verified_sha256,
        )
    except (ApprovalError, ValueError) as exc:
        _audit_safely(
            event_type="security.approval_registration_failed",
            severity="high",
            description=(
                "Update passed ingestion validation but could not be "
                "registered for approval. Aggregation is not authorized."
            ),
            client_id=envelope.client_id,
            update_id=envelope.update_id,
        )
        raise ApprovalRegistrationError(
            "Update could not enter the approval queue."
        ) from exc

    _audit_safely(
        event_type="security.update_authenticated",
        severity="info",
        description=(
            "Update passed integrity, authorization, signature, "
            "deserialization, model-schema, policy, and replay checks."
        ),
        client_id=envelope.client_id,
        update_id=envelope.update_id,
    )

    _audit_safely(
        event_type="security.update_pending_approval",
        severity="info",
        description=(
            f"Update registered with status {approval_record.status.value}. "
            "Aggregation is not authorized."
        ),
        client_id=envelope.client_id,
        update_id=envelope.update_id,
    )

    return {
        "update_id": envelope.update_id,
        "client_id": envelope.client_id,
        "model_version": envelope.model_version,
        "round_number": envelope.round_number,
        "payload_size_bytes": len(payload),
        "payload_sha256": verified_sha256,
        "integrity_status": "verified",
        "authentication_status": "verified",
        "replay_status": "accepted",
        "serialization_status": "verified",
        "schema_status": "verified",
        "policy_status": "accepted",
        "ingestion_status": "validated",
        "approval_status": approval_record.status.value,
        "aggregation_status": "not_authorized",
        "tensor_count": len(state_dict),
        "tensor_names": list(state_dict.keys()),
        "state_dict": state_dict,
    }


def deserialize_authenticated_update(
    payload: bytes,
    *,
    max_total_bytes: int = MAX_UPDATE_BYTES,
) -> dict[str, object]:
    """Safely deserialize an NPZ payload."""
    try:
        state_dict = deserialize_state_dict(
            payload,
            max_total_bytes=max_total_bytes,
        )
    except SerializationError:
        logger.warning("Authenticated update failed NPZ deserialization.")
        raise

    return {
        "tensor_count": len(state_dict),
        "tensor_names": list(state_dict.keys()),
        "state_dict": state_dict,
    }
