
"""Application service for validating incoming federated-learning updates."""

import logging
from dataclasses import asdict

from sqlalchemy.exc import SQLAlchemyError

from audit.service import record_audit_event
from core.config import (
    TRUST_MODE_COORDINATOR_VERIFIED,
    get_detection_config,
    get_high_risk_action,
    get_sample_count_trust_mode,
)
from core.crypto import verify_envelope_signature
from core.key_registry import get_trusted_key
from core.replay_protection import (
    ReplayProtectionError,
    is_reservation_finalized,
    mark_reservation_finalized_in_memory,
    release_update_reservation,
    reserve_update,
)
from detection.rule_based import (
    RuleBasedDetectionConfig,
    detect_update_anomalies,
)
from enforcement.approval_service import (
    ApprovalError,
    get_update_record,
    record_ingestion_audit_result,
    register_and_finalize_validated_update,
)
from features.model_schema import validate_against_registered_schema
from features.update_features import extract_update_features
from ingestion.payload import PayloadIntegrityError, verify_payload
from ingestion.sample_count_provider import (
    SampleCountMismatchError,
    SampleCountProvider,
    SampleCountVerificationError,
    resolve_sample_count,
)
from ingestion.schemas import UpdateEnvelope
from ingestion.serialization import SerializationError, deserialize_state_dict
from policy.detection_approval_policy import (
    ApprovalAction,
    select_initial_approval_status,
)
from policy.model_update_policy import (
    ModelUpdatePolicy,
    evaluate_update_policy,
)

logger = logging.getLogger(__name__)

MAX_UPDATE_BYTES = 10_000_000

# Optional trusted sample-count provider.  None = no independent verification.
# Client-claimed values are stored with provenance "client_claimed".
# Configure via configure_sample_count_provider() before accepting updates.
_sample_count_provider: SampleCountProvider | None = None


def configure_sample_count_provider(provider: SampleCountProvider | None) -> None:
    """Replace the module-level sample-count provider (test / startup hook)."""
    global _sample_count_provider
    _sample_count_provider = provider


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


class ReplayReservationFinalizationError(RuntimeError):
    """Raised when a registered update cannot finalize its replay reservation."""


class DetectionConfigurationError(RuntimeError):
    """Raised when required detector or risk-policy configuration is invalid."""


def _audit_safely(
    *,
    event_type: str,
    severity: str,
    description: str,
    client_id: str | None = None,
    update_id: str | None = None,
) -> bool:
    """Record an audit event without masking the original result.

    Returns True if the audit event was persisted, False if persistence failed.
    """
    try:
        record_audit_event(
            event_type=event_type,
            severity=severity,
            description=description,
            client_id=client_id,
            update_id=update_id,
        )
        return True
    except Exception:
        logger.exception(
            "Audit persistence failed for event_type=%s",
            event_type,
        )
        return False


def validate_incoming_update(
    payload: bytes,
    envelope: UpdateEnvelope,
    *,
    policy: ModelUpdatePolicy,
    detection_config: RuleBasedDetectionConfig | None = None,
    high_risk_action: ApprovalAction | None = None,
    trust_mode: str | None = None,
) -> dict[str, object]:
    """Validate an update, run anomaly detection, and register for approval.

    Passing ingestion validation does not authorize aggregation.
    """
    failed_audit_events: list[str] = []

    def _record_audit(event_type: str, severity: str, description: str) -> bool:
        ok = _audit_safely(
            event_type=event_type,
            severity=severity,
            description=description,
            client_id=envelope.client_id,
            update_id=envelope.update_id,
        )
        if not ok:
            failed_audit_events.append(event_type)
        return ok

    try:
        verified_sha256 = verify_payload(payload, envelope)
    except PayloadIntegrityError:
        _record_audit(
            event_type="security.payload_integrity_failed",
            severity="high",
            description="Incoming payload failed integrity verification.",
        )
        raise

    trusted_key = get_trusted_key(envelope.signing_key_id)

    if trusted_key is None:
        _record_audit(
            event_type="security.unknown_signing_key",
            severity="high",
            description="Update references an unregistered signing key.",
        )
        raise UpdateAuthenticationError("Unknown signing key")

    if trusted_key.client_id != envelope.client_id:
        _record_audit(
            event_type="security.client_key_mismatch",
            severity="high",
            description="Signing key is not authorized for the claimed client.",
        )
        raise UpdateAuthenticationError(
            "Signing key is not authorized for this client"
        )

    if not verify_envelope_signature(envelope, trusted_key.public_key):
        _record_audit(
            event_type="security.signature_verification_failed",
            severity="high",
            description="Update envelope signature verification failed.",
        )
        raise UpdateAuthenticationError("Invalid update signature")

    if trusted_key.max_sample_count is None:
        _record_audit(
            event_type="security.sample_count_limit_missing",
            severity="high",
            description="Trusted signing key has no server-configured sample-count limit.",
        )
        raise UpdatePolicyRejectedError(
            "sample_count_limit_missing",
            "Trusted sample-count limit is not configured for this signing key.",
        )

    if envelope.sample_count > trusted_key.max_sample_count:
        _record_audit(
            event_type="security.sample_count_limit_exceeded",
            severity="high",
            description="Signed update sample count exceeds its trusted key limit.",
        )
        raise UpdatePolicyRejectedError(
            "sample_count_limit_exceeded",
            "Update sample count exceeds the server-configured key limit.",
        )

    _trust_mode = trust_mode if trust_mode is not None else get_sample_count_trust_mode()
    _require_verified = _trust_mode == TRUST_MODE_COORDINATOR_VERIFIED

    try:
        sc_result = resolve_sample_count(
            client_claimed=envelope.sample_count,
            provider=_sample_count_provider,
            client_id=envelope.client_id,
            update_id=envelope.update_id,
            round_number=envelope.round_number,
            require_verified=_require_verified,
        )
    except SampleCountMismatchError as exc:
        _record_audit(
            event_type="security.sample_count_mismatch",
            severity="high",
            description=f"Provider sample count differs from client claim: {exc}",
        )
        raise UpdatePolicyRejectedError(
            "sample_count_mismatch",
            "Trusted provider count does not match the client-claimed sample count.",
        ) from exc
    except SampleCountVerificationError as exc:
        _record_audit(
            event_type="security.sample_count_verification_required",
            severity="high",
            description=f"Verified sample count required but unavailable: {exc}",
        )
        raise UpdatePolicyRejectedError(
            "sample_count_verification_required",
            "A verified sample count is required by policy but could not be obtained.",
        ) from exc

    try:
        state_dict = deserialize_state_dict(
            payload,
            max_total_bytes=MAX_UPDATE_BYTES,
        )
    except SerializationError:
        _record_audit(
            event_type="security.serialization_failed",
            severity="high",
            description=(
                "Authenticated payload failed safe model-weight deserialization."
            ),
        )
        raise

    schema_result = validate_against_registered_schema(
        state_dict,
        model_version=envelope.model_version,
        max_total_bytes=MAX_UPDATE_BYTES,
    )

    if not schema_result.accepted:
        _record_audit(
            event_type="security.model_schema_rejected",
            severity="high",
            description=schema_result.reason,
        )
        raise ModelSchemaValidationError(schema_result.reason)

    decision = evaluate_update_policy(envelope, policy)

    if not decision.accepted:
        _record_audit(
            event_type=f"security.policy_rejected.{decision.reason_code}",
            severity="high",
            description=decision.reason,
        )
        raise UpdatePolicyRejectedError(
            decision.reason_code,
            decision.reason,
        )

    # Reserve the authenticated, policy-compliant update before spending work
    # on statistical feature extraction or detection.
    try:
        reservation_token = reserve_update(envelope)
    except ReplayProtectionError:
        _record_audit(
            event_type="security.replay_detected",
            severity="high",
            description="Update rejected by replay protection.",
        )
        raise

    try:
        try:
            active_detection_config = detection_config or get_detection_config()
            active_high_risk_action = (
                high_risk_action
                if high_risk_action is not None
                else get_high_risk_action()
            )
        except (TypeError, ValueError) as exc:
            raise DetectionConfigurationError(
                "Required detection or risk-policy configuration is invalid."
            ) from exc

        features = extract_update_features(
            state_dict,
            reference_state_dict=None,
        )
        detection_result = detect_update_anomalies(
            features,
            config=active_detection_config,
        )
        initial_status = select_initial_approval_status(
            detection_result.severity,
            high_risk_action=active_high_risk_action,
        )
    except Exception:
        released = release_update_reservation(
            client_id=envelope.client_id,
            update_id=envelope.update_id,
            token=reservation_token,
        )
        if not released:
            logger.error(
                "Could not release replay reservation after detection failure "
                "for client_id=%s update_id=%s",
                envelope.client_id,
                envelope.update_id,
            )
        raise

    if detection_result.suspicious:
        _record_audit(
            event_type="security.anomaly_detected",
            severity=detection_result.severity.lower(),
            description=(
                f"Update flagged with risk score {detection_result.risk_score} "
                f"({detection_result.severity}): {'; '.join(detection_result.reasons)}"
            ),
        )
        if initial_status == "quarantined":
            approval_reason = (
                f"Security validation passed; ANOMALY FLAGGED "
                f"(score={detection_result.risk_score}, "
                f"severity={detection_result.severity}): "
                f"{'; '.join(detection_result.reasons)} "
                "Quarantined for review; anomaly score is not proof of malicious intent."
            )
        elif detection_result.severity in {"MEDIUM", "HIGH", "CRITICAL"}:
            approval_reason = (
                f"Security validation passed; human review required "
                f"(score={detection_result.risk_score}, "
                f"severity={detection_result.severity}): "
                f"{'; '.join(detection_result.reasons)}"
            )
        else:
            approval_reason = (
                f"Security validation passed; ANOMALY FLAGGED "
                f"(score={detection_result.risk_score}, "
                f"severity={detection_result.severity}): "
                f"{'; '.join(detection_result.reasons)} Approval is still required."
            )
    else:
        _record_audit(
            event_type="security.anomaly_clean",
            severity="info",
            description=(
                f"Update feature statistics normal (risk score {detection_result.risk_score})."
            ),
        )
        approval_reason = (
            f"Security validation passed; risk_score={detection_result.risk_score} "
            f"({detection_result.severity}). Approval is still required."
        )

    # Note if any prior audit event failed
    if failed_audit_events:
        approval_reason += (
            f" [AUDIT_PERSISTENCE_FAILED for: {', '.join(failed_audit_events)}]"
        )

    # Register the approval row and finalize the replay reservation atomically.
    # Either both the update_approvals INSERT and the replay_records UPDATE commit
    # together, or both roll back.  There is no window where the approval row
    # exists while the replay record remains unfinalized.
    try:
        approval_record = register_and_finalize_validated_update(
            update_id=envelope.update_id,
            client_id=envelope.client_id,
            model_version=envelope.model_version,
            round_number=envelope.round_number,
            sample_count_result=sc_result,
            payload_sha256=verified_sha256,
            reason=approval_reason,
            initial_status=initial_status,
            risk_score=detection_result.risk_score,
            risk_severity=detection_result.severity,
            suspicious=detection_result.suspicious,
            anomaly_reasons=detection_result.reasons,
            detector_version="rule-based-v1",
            detector_config={
                **asdict(active_detection_config),
                "high_risk_action": active_high_risk_action,
            },
            reservation_token=reservation_token,
        )
    except (ApprovalError, ValueError, SQLAlchemyError) as exc:
        # Attempt to release.  release_update_reservation() now detects the
        # ambiguous-commit case (DB row finalized=True, DELETE rowcount=0) by
        # syncing entry.finalized=True and returning False.
        try:
            reservation_released = release_update_reservation(
                client_id=envelope.client_id,
                update_id=envelope.update_id,
                token=reservation_token,
            )
        except Exception:
            reservation_released = False
            logger.exception(
                "Replay reservation release raised after combined registration "
                "failure for client_id=%s update_id=%s",
                envelope.client_id,
                envelope.update_id,
            )

        # Ambiguous-commit recovery: if the reservation is now finalized despite
        # the exception, the DB transaction may have committed before the connection
        # dropped.  Verify by checking for the approval record in the DB.
        if not reservation_released and is_reservation_finalized(
            client_id=envelope.client_id,
            update_id=envelope.update_id,
        ):
            try:
                recovered_record = get_update_record(
                    client_id=envelope.client_id,
                    update_id=envelope.update_id,
                )
            except Exception:
                recovered_record = None

            if recovered_record is not None:
                # Verify that the committed record matches this exact request.
                # Due to the UNIQUE constraint on (client_id, update_id) only one
                # approval row can ever exist per pair, so a mismatch here would
                # indicate an internal consistency error rather than a collision.
                if (
                    recovered_record.payload_sha256 != verified_sha256
                    or recovered_record.model_version != envelope.model_version
                    or recovered_record.round_number != envelope.round_number
                ):
                    logger.error(
                        "Ambiguous-commit recovery: committed record fields do not "
                        "match in-flight request for client_id=%s update_id=%s — "
                        "manual review required.",
                        envelope.client_id,
                        envelope.update_id,
                    )
                    _record_audit(
                        event_type="security.approval_registration_failed",
                        severity="high",
                        description=(
                            "Update passed ingestion validation but could not be "
                            "registered for approval. Aggregation is not authorized. "
                            "Ambiguous-commit recovery: committed record fields do not "
                            "match in-flight request (manual review required)."
                        ),
                    )
                    raise ApprovalRegistrationError(
                        "Update could not enter the approval queue."
                    ) from exc

                # Both the approval INSERT and replay finalization committed.
                # The exception was caused by a lost acknowledgment, not a rollback.
                logger.warning(
                    "Ambiguous commit recovered for client_id=%s update_id=%s: "
                    "approval row and finalized replay record both exist despite "
                    "SQLAlchemyError; treating as successful registration.",
                    envelope.client_id,
                    envelope.update_id,
                )
                approval_record = recovered_record
                # Fall through to the success path below the except block.
            else:
                # Replay record is finalized but no approval row exists —
                # cannot determine safe outcome; require manual review.
                logger.error(
                    "Replay reservation is finalized but no approval record found "
                    "for client_id=%s update_id=%s — manual review required.",
                    envelope.client_id,
                    envelope.update_id,
                )
                _record_audit(
                    event_type="security.approval_registration_failed",
                    severity="high",
                    description=(
                        "Update passed ingestion validation but could not be "
                        "registered for approval. Aggregation is not authorized. "
                        "Replay reservation is finalized but no approval record "
                        "was found (manual review required)."
                    ),
                )
                raise ApprovalRegistrationError(
                    "Update could not enter the approval queue."
                ) from exc
        else:
            if not reservation_released:
                logger.error(
                    "Replay reservation remains held after combined registration "
                    "failure for client_id=%s update_id=%s",
                    envelope.client_id,
                    envelope.update_id,
                )
            _record_audit(
                event_type="security.approval_registration_failed",
                severity="high",
                description=(
                    "Update passed ingestion validation but could not be "
                    "registered for approval. Aggregation is not authorized. "
                    + (
                        "Replay reservation was rolled back."
                        if reservation_released
                        else "Replay reservation release failed and remains held."
                    )
                ),
            )
            raise ApprovalRegistrationError(
                "Update could not enter the approval queue."
            ) from exc

    # Both the approval INSERT and replay finalization committed atomically
    # (or recovered via ambiguous-commit reconciliation above).
    # Update the in-memory cache so is_reservation_finalized() fast-path works.
    # A False return (e.g. after a process restart or ambiguous-commit recovery
    # where entry.finalized was already synced) is non-critical: the DB row is
    # already finalized and the DB fallback in is_reservation_finalized() confirms.
    mark_reservation_finalized_in_memory(
        client_id=envelope.client_id,
        update_id=envelope.update_id,
        token=reservation_token,
    )

    _record_audit(
        event_type="security.update_authenticated",
        severity="info",
        description=(
            "Update passed integrity, authorization, signature, "
            "deserialization, model-schema, policy, and replay checks."
        ),
    )

    if approval_record.status.value == "quarantined":
        _record_audit(
            event_type="security.update_quarantined",
            severity="high",
            description=(
                "Update was quarantined by the risk policy for human review. "
                "Aggregation is not authorized."
            ),
        )
    else:
        _record_audit(
            event_type="security.update_pending_approval",
            severity="info",
            description=(
                f"Update registered with status {approval_record.status.value}. "
                "Aggregation is not authorized."
            ),
        )

    audit_status = "failed" if failed_audit_events else "persisted"
    try:
        record_ingestion_audit_result(
            client_id=envelope.client_id,
            update_id=envelope.update_id,
            audit_status=audit_status,
            audit_failures=tuple(failed_audit_events),
        )
    except Exception:
        logger.exception(
            "Could not persist final audit outcome for client_id=%s update_id=%s",
            envelope.client_id,
            envelope.update_id,
        )
        if "security.audit_status_persistence_failed" not in failed_audit_events:
            failed_audit_events.append("security.audit_status_persistence_failed")
        audit_status = "failed"

    return {
        "update_id": envelope.update_id,
        "client_id": envelope.client_id,
        "model_version": envelope.model_version,
        "round_number": envelope.round_number,
        "sample_count": envelope.sample_count,
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
        "risk_score": detection_result.risk_score,
        "severity": detection_result.severity,
        "suspicious": detection_result.suspicious,
        "anomaly_reasons": list(detection_result.reasons),
        "audit_status": audit_status,
        "audit_failures": list(failed_audit_events),
        "features": features,
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
