# FinSentinel Threat Model

## Scope

This document covers threats to FinSentinel's role as a security layer for
federated-learning model updates. It does not cover threats to the FL training
process itself, the FL coordinator, or client devices.

---

## Assets

| Asset | Value |
|---|---|
| Model update integrity | Prevent poisoned/backdoored models from reaching aggregation |
| Audit trail | Tamper-evident record of all security events |
| Operator credentials | Prevent unauthorized approval of malicious updates |
| Client signing keys | Prevent impersonation of legitimate clients |

---

## Threat Actors

| Actor | Capability | Goal |
|---|---|---|
| Malicious FL client | Controls one or more registered clients | Inject poisoned updates |
| Insider (operator) | Access to operator token | Approve malicious updates, suppress alerts |
| Network attacker | MITM between client and server | Replay valid updates, intercept audit events |
| Compromised SIEM | Controls the webhook endpoint | SSRF attacks via crafted webhook URLs |

---

## Mitigations by Threat

### T1: Model Poisoning via Large Weight Updates

**Attack**: Client sends update with anomalously large weights.

**Mitigations**:
- Rule-based detection flags updates exceeding L2 norm, std, or mean thresholds.
- All flagged updates are routed to operator approval before aggregation.
- Anomaly detection config in `detection/rule_based.py`; thresholds in env vars.

**Residual risk**: False negative if poisoning stays within thresholds. Production
calibration required (see `configs/detection_dataset_inventory.md`).

---

### T2: Replay Attack

**Attack**: Attacker captures a valid signed update and resends it.

**Mitigation**: `(client_id, update_id)` reservation is atomic. Second submission
returns HTTP 409. Replay records stored in `replay_records` table.

**Residual risk**: None within a single FinSentinel deployment. Cross-deployment
replay not in scope.

---

### T3: Signature Forgery

**Attack**: Client sends update signed with an unregistered key, or forges a
signature.

**Mitigation**: Ed25519 signature verification against registered public keys
(`core/key_registry.py`). Verification failure returns HTTP 401.

**Residual risk**: Key compromise. Rotate keys and revoke via `clear_trusted_keys()`
or targeted DB deletion.

---

### T4: Stale Update Injection

**Attack**: Client resends an old valid update from a previous round to influence
the current aggregation.

**Mitigation**: Policy checks `created_at` timestamp against `FINSENTINEL_MAX_UPDATE_AGE_SECONDS`
(default 900 s = 15 min). Old updates return HTTP 403.

---

### T5: Audit Log Suppression

**Attack**: Attacker deletes or truncates audit records to hide their activity.

**Mitigation**: Audit events are written to the database in the same transaction as
the ingestion operation (can't succeed without audit). External delivery to SIEM via
the outbox/webhook pipeline provides an independent copy. Dead-lettered events trigger
operator alert.

**Residual risk**: If the SIEM webhook is not configured, only the DB copy exists.
Configure `FINSENTINEL_AUDIT_WEBHOOK_URL` for external durability.

---

### T6: SSRF via Webhook URL

**Attack**: Operator (or config injection) sets `FINSENTINEL_AUDIT_WEBHOOK_URL` to
a private IP, targeting internal services.

**Mitigation**: `_validate_delivery_url()` in `audit/delivery.py` blocks:
- RFC 1918 private ranges (10.x, 172.16-31.x, 192.168.x)
- Loopback (127.x, `::1`)
- Link-local (169.254.x)
- Multicast (224.x+)
- `localhost` hostname
- Non-HTTP(S) schemes

**Residual risk**: DNS rebinding — URL resolves to public IP at validation time,
then to private IP at delivery time. Mitigate with DNS pinning at the OS/network level.

---

### T7: Sample Count Inflation

**Attack**: Client claims an inflated `sample_count` to gain outsized influence in
FedAvg aggregation.

**Mitigation**: 
- `max_sample_count` per registered key caps the claimed count.
- `coordinator_verified` trust mode cross-checks with the FL coordinator.
- `client_claimed` mode (default) trusts the client's claimed count — only use if
  clients are trusted or if `max_sample_count` limits are enforced.

---

### T8: Operator Token Theft

**Attack**: Attacker obtains `FINSENTINEL_OPERATOR_TOKEN` and approves malicious updates.

**Mitigation**:
- Token is bearer-only; all operator endpoints require it.
- Dashboard never returns the token value in its response.
- Rotate by setting a new `FINSENTINEL_OPERATOR_TOKEN` and restarting the service.

**Residual risk**: No token rotation without restart. Consider short-lived tokens
(JWT) for future hardening.

---

## Deployment-Dependent Mitigations

The following mitigations require operational configuration and are NOT enforced
by the application code alone:

| Control | Configuration |
|---|---|
| TLS in transit | nginx TLS config in `configs/nginx.conf` |
| External audit log durability | `FINSENTINEL_AUDIT_WEBHOOK_URL` set to SIEM |
| Rate limiting at network layer | nginx `limit_req_zone` |
| Concurrency limits | `FINSENTINEL_MAX_CONCURRENT_INGESTION` |
| Body size limits | nginx `client_max_body_size` + `FINSENTINEL_BODY_READ_TIMEOUT_SECONDS` |
| Dead-letter alert response | Operator monitoring of `outbox.alert` in dashboard |
