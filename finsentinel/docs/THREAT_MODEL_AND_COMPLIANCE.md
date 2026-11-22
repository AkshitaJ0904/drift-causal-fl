# FinSentinel — Threat Model and Compliance Mapping

> Local development evaluation copy. Not a certified compliance assessment.

---

## STRIDE Threat Model

| Threat | Attack scenario | Control | Evidence |
|--------|----------------|---------|----------|
| **Spoofing** | Rogue FL client submits update claiming another client's identity | Ed25519 signature + client-key registry (rule 100113); client–key mismatch check (rule 100114) | pytest: `test_signature_verification_failed`, `test_client_key_mismatch`; VAPT F-04 |
| **Tampering** | Payload modified in transit after signing | SHA-256 payload integrity check on ingestion (rule 100112) | pytest: `test_payload_integrity_failed`; Wazuh rule 100112 |
| **Repudiation** | Client denies submitting a malicious update | Every gateway event written to tamper-evident audit outbox → SIEM (Wazuh) before any decision | check_stack.py outbox health; VAPT delivery verified |
| **Information disclosure** | Stack trace or token leaked in API response | Error handler strips tracebacks; token stored in env, not code; whitelist-only response fields | pytest: `test_no_secret_fields_leaked`; VAPT confirms no stack traces |
| **Denial of service** | Flood of large payloads exhausts server | 10 MB body-size limit middleware; rate-limit middleware (placeholder; see Limitations) | pytest: `test_body_size_limit_enforced` |
| **Elevation of privilege** | Replay a previously accepted update | Idempotency-nonce replay detection (rule 100105) | pytest: `test_replay_detected` |
| **Elevation of privilege** | Brute-force operator token | Wazuh correlation rule 100140 fires after 5 failures/60 s | Wazuh Security Center rule 100140 |
| **Tampering** | Malicious model schema to bypass shape checks | Pydantic schema validation on ingestion (rule 100107) | pytest: `test_model_schema_rejected` |

---

## Control Mapping

### ISO 27001:2022 Annex A

| Control area | FinSentinel implementation |
|---|---|
| A.8.3 Information access restriction | Operator token (HMAC compare\_digest); all API endpoints require auth |
| A.8.16 Monitoring activities | Audit outbox → Wazuh SIEM; all security events emitted as JSONL |
| A.8.24 Use of cryptography | Ed25519 payload signing; SHA-256 integrity; nonce replay protection |
| A.8.28 Secure coding | Whitelist-only response fields; Pydantic schema validation; ruff/mypy CI |
| A.5.37 Documented operating procedures | HOW\_TO\_LOGIN.md; AGENTref.md; this document |

### NIST Cybersecurity Framework (CSF 2.0)

| Function | Control |
|---|---|
| **Identify** | VAPT suite (67 tests); threat model (this doc); detection configuration page |
| **Protect** | Ed25519 signatures; replay nonce; schema validation; approval gate (segregation of duties) |
| **Detect** | Wazuh 30 rules (100100–100140); brute-force correlation; anomaly score layer |
| **Respond** | Operator approval/reject/quarantine with mandatory audit reason; dead-letter alert |
| **Recover** | Dead-letter recovery UI; audit outbox replay; Wazuh event archive |

### OWASP API Security Top 10

| Risk | Mitigation |
|---|---|
| API1 Broken Object Level Authorization | Updates scoped by client\_id; operator endpoints require token |
| API2 Broken Authentication | HMAC constant-time token compare; Wazuh brute-force rule 100140 |
| API3 Broken Object Property Level Authorization | Whitelist response fields; no raw weights returned |
| API5 Broken Function Level Authorization | Operator-only endpoints (`/updates/*/approve` etc.) require Bearer token |
| API8 Security Misconfiguration | No debug routes in prod; `FINSENTINEL_OPERATOR_TOKEN` required at startup |
| API10 Unsafe Consumption of APIs | Pydantic input validation; schema rejection before ML processing |

---

## Limitations and Future Work

- **Local development only** — TLS not configured; default Wazuh admin credentials; no HSM/PKI.
- **No operator rate limit (F-01)** — Approval endpoints are not rate-limited; remediation: add per-IP rate limit middleware.
- **Failed auth not audited (F-02)** — 401 responses from `require_operator_auth` are not emitted to the SIEM outbox.
- **Aggregation not audited (F-03)** — The aggregation endpoint does not emit a security event on completion.
- **Isolation Forest not wired** — Layer 2 ML anomaly detection is defined in schema but not connected to the ingestion pipeline.
- **No poisoning-detection metrics** — Model accuracy drift and contribution distance are not tracked post-aggregation.
- **No active response / auto key revoke** — The gateway flags anomalies but does not automatically revoke client keys.
- **HTTPS** — Production deployment must terminate TLS in front of the FastAPI gateway.
