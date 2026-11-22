"""Map FinSentinel JSONL event_type strings to Wazuh rule metadata.

Rule IDs, levels and descriptions are sourced from
deploy/wazuh/rules/finsentinel_rules.xml.  The drift test
(tests/test_security_events.py) verifies every rule_id here exists in
the XML with the same level.

Severity buckets: level <= 4 → Low, 5-9 → Medium, 10-12 → High, >= 13 → Critical.
Rule 100140 (brute-force) is a Wazuh correlation rule, not an event_type,
so it is not mapped here — the Security Events page explains this.
"""

from __future__ import annotations


def level_to_severity(level: int) -> str:
    """Map a Wazuh rule level to a severity label.

    Buckets: level<=4→Low, 5-9→Medium, 10-12→High, >=13→Critical.
    """
    if level <= 4:
        return "Low"
    if level <= 9:
        return "Medium"
    if level <= 12:
        return "High"
    return "Critical"


def _e(rule_id: str, level: int, plain: str) -> dict:
    return {
        "rule_id": rule_id,
        "level": level,
        "severity": level_to_severity(level),
        "plain_english": plain,
    }


# Extra educational fields for the Detection Rules catalog UI.
# Keys match rule_id; values merged in by api/security_events.py catalog endpoint.
CATALOG_EXTRAS: dict[str, dict] = {
    "100101": {
        "why_it_matters": "Confirms the update passed all gateway checks and is now queued for operator review.",  # noqa: E501
        "what_to_do": "No action required. Review the update in the Approvals queue.",
        "example": "Client bank-node-01 submitted a valid round-7 update.",
    },
    "100103": {
        "why_it_matters": "The anomaly detector flagged an unusually large gradient shift — could be benign drift or a poisoning attempt.",  # noqa: E501
        "what_to_do": "Review the update's risk score and L2 norm in the Approvals page. Approve if the deviation is explained.",  # noqa: E501
        "example": "L2 norm 142.3 exceeded threshold 100.0 for client bank-node-02.",
    },
    "100104": {
        "why_it_matters": "The update's cryptographic signature did not match the registered Ed25519 public key — the payload may have been tampered with or sent from an unauthorized device.",  # noqa: E501
        "what_to_do": "Revoke the client's key immediately. Investigate how the key or payload was accessed.",  # noqa: E501
        "example": "Invalid signature on update from client bank-node-03.",
    },
    "100105": {
        "why_it_matters": "The same idempotency key was submitted twice — classic replay attack pattern.",  # noqa: E501
        "what_to_do": "Investigate the client. Check whether the replay was accidental (buggy retry logic) or deliberate.",  # noqa: E501
        "example": "Nonce abc123 seen before — update from bank-node-04 blocked.",
    },
    "100112": {
        "why_it_matters": "The SHA-256 hash of received bytes did not match the declared hash — the payload was altered in transit.",  # noqa: E501
        "what_to_do": "Treat as a potential man-in-the-middle attack. Revoke the client and audit network path.",  # noqa: E501
        "example": "Expected hash a1b2c3..., got d4e5f6... for client bank-node-05.",
    },
    "100113": {
        "why_it_matters": "No registered key matches the signing key used — could be a compromised or rogue device.",  # noqa: E501
        "what_to_do": "Do not register the unknown key without out-of-band verification. Investigate the source.",  # noqa: E501
        "example": "Key fingerprint 9a8b7c... not found in Trusted Key Registry.",
    },
    "100114": {
        "why_it_matters": "The signing key is registered to a different client_id than the one in the request header — identity spoofing attempt.",  # noqa: E501
        "what_to_do": "Investigate both the key owner and the requesting client. Flag for incident response.",  # noqa: E501
        "example": "Key registered to bank-node-01 used in request claiming client bank-node-06.",
    },
    "100140": {
        "why_it_matters": "Wazuh correlated 5+ failed operator-auth attempts within 60 seconds — brute-force attack on the operator token.",  # noqa: E501
        "what_to_do": "Rotate the operator token immediately. Block the source IP at the network layer.",  # noqa: E501
        "example": "5 failed /api/v1/operator/* requests from 192.0.2.10 within 60 s.",
    },
}


# event_type (exact) → rule metadata
_EXACT: dict[str, dict] = {
    "security.update_authenticated": _e("100101", 3, "Update authenticated and queued for review"),
    "security.update_pending_approval": _e("100102", 3, "Update pending operator approval"),
    "security.update_quarantined": _e("100103", 10, "Update auto-quarantined — high risk score"),
    "security.signature_verification_failed": _e(
        "100104", 12, "Forged update blocked — invalid signature"
    ),
    "security.replay_detected": _e("100105", 12, "Replay attack blocked"),
    "security.anomaly_detected": _e(
        "100106", 10, "Statistical anomaly detected in model update"
    ),
    "security.model_schema_rejected": _e(
        "100107", 10, "Schema violation blocked — wrong tensor shape or dtype"
    ),
    "security.sample_count_limit_exceeded": _e(
        "100109", 10, "Sample count exceeds the per-key server limit"
    ),
    "security.sample_count_limit_missing": _e(
        "100110", 12, "Trusted key has no sample-count limit — config gap"
    ),
    "security.approval_registration_failed": _e(
        "100111", 7, "Failed to register update for approval (DB error)"
    ),
    "security.payload_integrity_failed": _e(
        "100112", 10, "Tampered payload blocked — SHA-256 mismatch"
    ),
    "security.unknown_signing_key": _e("100113", 12, "Unknown signing key blocked"),
    "security.client_key_mismatch": _e(
        "100114", 12, "Identity mismatch — key registered to different client"
    ),
    "security.sample_count_mismatch": _e(
        "100115", 10, "Declared sample count differs from server-measured count"
    ),
    "security.sample_count_verification_required": _e(
        "100116", 10, "Sample count verification required before aggregation"
    ),
    "security.serialization_failed": _e("100117", 7, "Model update serialization failed"),
    "security.anomaly_clean": _e("100118", 3, "Anomaly detector found no issues"),
    "security.audit_status_persistence_failed": _e(
        "100119", 7, "Failed to persist audit status (DB write error)"
    ),
    "operator.update_approved": _e("100120", 3, "Operator approved update"),
    "operator.update_rejected": _e("100121", 7, "Operator rejected update"),
    "operator.update_quarantined": _e("100122", 10, "Operator quarantined update"),
    "operator.approve_requested": _e("100123", 3, "Operator initiated approval request"),
    "operator.reject_requested": _e("100124", 7, "Operator initiated rejection"),
    "operator.quarantine_requested": _e("100125", 10, "Operator initiated quarantine"),
    "schema.registered": _e("100130", 3, "Model schema registered"),
    "key.registered": _e("100131", 3, "Trusted client signing key registered"),
}

# Prefix matches (checked when exact match fails, longest prefix wins).
# security.policy_rejected.<reason_code> → rule 100108
_PREFIXES: list[tuple[str, dict]] = [
    ("security.policy_rejected.", _e("100108", 10, "Model update rejected by policy")),
]


def lookup(event_type: str) -> dict | None:
    """Return rule metadata for event_type, or None if unmapped."""
    exact = _EXACT.get(event_type)
    if exact is not None:
        return exact
    for prefix, meta in _PREFIXES:
        if event_type.startswith(prefix):
            return meta
    return None


def all_exact_mappings() -> dict[str, dict]:
    """Return all exact event_type → metadata entries (for testing)."""
    return dict(_EXACT)


def prefix_mappings() -> list[tuple[str, dict]]:
    """Return all prefix entries (for testing)."""
    return list(_PREFIXES)
