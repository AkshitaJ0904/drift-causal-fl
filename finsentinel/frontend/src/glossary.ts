/** Single source of truth for jargon terms used in Explain tooltips. */
export const GLOSSARY: Record<string, { short: string; detail: string }> = {
  'client_id': {
    short: 'Unique identifier for a federated learning participant.',
    detail: 'A string (e.g. "bank-node-01") assigned when a participant registers their signing key. Every model update carries the client_id so the gateway can verify ownership.',
  },
  'anomaly_score': {
    short: 'Statistical distance score from the trained baseline (0 = normal, higher = suspicious).',
    detail: 'Computed by comparing the L2 norm of incoming gradients against the distribution seen in prior clean rounds. Scores above the configured threshold trigger a quarantine or rejection event.',
  },
  'l2_norm': {
    short: 'Euclidean length of a gradient vector — a proxy for update magnitude.',
    detail: 'Unusually large L2 norms indicate a client may be injecting scaled gradients (a poisoning technique). The gateway checks this against a per-key limit set at registration time.',
  },
  'signature': {
    short: 'Ed25519 cryptographic proof that the update came from the registered key.',
    detail: 'Clients sign the SHA-256 hash of their model payload with their Ed25519 private key. The gateway verifies using the public key in the Trusted Key Registry. A bad signature triggers rule 100104.',
  },
  'sha256': {
    short: 'SHA-256 hash of the model payload bytes, used to detect tampering in transit.',
    detail: 'The gateway recomputes the hash of received bytes and compares it against the declared hash. A mismatch triggers rule 100112 (payload integrity failure).',
  },
  'replay': {
    short: 'Attack where an old, valid update is re-submitted to manipulate training.',
    detail: 'Each update carries a unique idempotency key (nonce). The forwarder tracks seen keys in memory; a repeated key triggers rule 100105 and blocks the update.',
  },
  'nonce': {
    short: 'One-time identifier on each update that prevents replay attacks.',
    detail: 'Short for "number used once". Clients generate a fresh nonce per submission. The gateway rejects any nonce it has already processed.',
  },
  'schema': {
    short: 'Declared tensor names, shapes, and dtypes a model update must match.',
    detail: 'Registered via scripts/register_model_schema.py. Updates whose tensor layout does not match a registered schema are rejected at ingestion (rule 100107), before any ML processing happens.',
  },
  'quarantine': {
    short: 'Update held pending operator review — not approved, not rejected.',
    detail: 'The gateway places high-risk updates in quarantine automatically (rule 100103) or via operator action. Quarantined updates do not enter aggregation. An operator must explicitly approve or reject them.',
  },
  'dead_letter': {
    short: 'Audit event that exhausted all delivery retries and cannot be forwarded.',
    detail: 'The outbox retries delivery up to 10 times with exponential back-off. If all attempts fail (e.g. the SIEM forwarder is down) the event is moved to the dead-letter queue. It will not be retried automatically — manual investigation is required.',
  },
  'outbox': {
    short: 'Durable queue that stores audit events before forwarding them to the SIEM.',
    detail: 'Implements the transactional outbox pattern: events are written to the database in the same transaction as the security decision, then a background worker forwards them. This guarantees no event is lost even if the SIEM is temporarily unreachable.',
  },
  'severity': {
    short: 'Urgency label derived from the Wazuh rule level (Low / Medium / High / Critical).',
    detail: 'Mapped by level: ≤4 → Low, 5–9 → Medium, 10–12 → High, ≥13 → Critical. Wazuh levels reflect event impact; the gateway uses them to decide whether to auto-quarantine or block.',
  },
  'mitre': {
    short: 'MITRE ATT&CK technique ID describing the attack class.',
    detail: 'The MITRE ATT&CK framework is a knowledge base of adversary tactics. Each Wazuh rule is tagged with the closest technique (e.g. T1565 — Data Manipulation). Used by the SOC for threat hunting and compliance reporting.',
  },
  'level': {
    short: 'Wazuh numeric rule level (1–15) indicating event impact.',
    detail: 'Higher levels = higher impact. The gateway\'s rules span levels 3–13. Level 3 = informational; 10–12 = security event requiring review; 13 = critical (brute-force correlation).',
  },
  'rule_id': {
    short: 'Wazuh rule identifier (100100–100140 for FinSentinel rules).',
    detail: 'Each security check in the gateway fires a Wazuh rule by ID. The ID appears in Wazuh dashboards, the SIEM log, and the Detection Rules catalog.',
  },
}

export type GlossaryKey = keyof typeof GLOSSARY
