# FinSentinel — Panel Q&A

**Author:** Jaivardhan Vajpai  
**Date:** 2026-11-21  
**Context:** B.Tech final-year project panel presentation

---

## Architecture & Design

**Q1. What problem does FinSentinel solve?**

Federated learning lets banks train a shared fraud-detection model without sharing raw transaction data. The risk is that a compromised client can poison the global model by submitting malicious weight updates. FinSentinel sits between FL clients and the aggregation server as a security gateway: it authenticates every update with Ed25519 signatures, verifies payload integrity with SHA-256, checks for replay attacks, enforces schema and policy rules, detects statistical anomalies, and gates all risky updates behind a human operator decision — before they ever reach the aggregator.

**Q2. Why Ed25519 specifically, and not RSA or ECDSA?**

Ed25519 is 256-bit elliptic-curve Schnorr with a fixed 64-byte signature — far smaller than RSA-2048 (256 bytes) and faster to verify. It is also immune to the small-subgroup and invalid-curve attacks that affect many ECDSA implementations. Because FL clients sign hundreds of model updates per training round, the constant-time and performance properties matter. The Go, Python, and Rust standard libraries all support it natively, so there is no dependency on a custom cipher.

**Q3. What is the approval gate and why is it exact-match?**

When an ingested update is flagged as high-risk (risk score above threshold or anomaly detected), the system stores a SHA-256 digest of the exact model weights submitted. When an operator approves, the aggregation service recomputes SHA-256 of the bytes it is about to aggregate and compares it to the stored digest. If they differ — even by a single bit — aggregation is rejected with 422. This prevents an adversary from submitting a benign update for approval and then substituting a poisoned payload once approval is granted.

**Q4. How does replay protection work?**

Two layers: an in-memory set of `(update_id, timestamp)` tuples (cleared on restart) and a database unique-constraint on the `replay_records` table. The in-memory set catches rapid replays within a single process lifetime. The database catches replays across restarts. Additionally, every update envelope includes a UTC timestamp and the ingestion service rejects updates whose timestamp is more than `FINSENTINEL_MAX_UPDATE_AGE_SECONDS` (default 86 400 s) old or more than `FINSENTINEL_MAX_FUTURE_CLOCK_SKEW_SECONDS` (default 300 s) in the future.

**Q5. Why SQLite for the VAPT test database instead of PostgreSQL?**

The VAPT suite needs a completely isolated, throwaway database — no interference with the development or production data. SQLite provides this with zero configuration: `start_vapt_backend.py` creates `vapt.db` in the project root, runs the test, and the file can be deleted after. For production the backend uses PostgreSQL 18.6; the SQLAlchemy ORM abstracts the difference, and all 748 non-VAPT backend tests also run on SQLite for the same reason.

---

## FL Approval Gate

**Q6. What happens when an operator approves an update?**

`POST /api/v1/updates/{client_id}/{update_id}/approve` with a mandatory `reason` string. The service: (1) fetches the pending approval record from the DB, (2) verifies the update is in `pending_approval` state, (3) transitions state to `approved`, (4) writes an `operator.update_approved` audit event to the outbox. The outbox worker then forwards the event to the SIEM forwarder, which delivers it to Wazuh via signed webhook and writes it to `finsentinel-siem.jsonl`. The reason is stored in the audit event and shown in the Security Center.

**Q7. Can a client force-approve its own update?**

No. The approval endpoints (`/approve`, `/reject`, `/quarantine`) are gated behind `require_operator_auth`, which validates the `FINSENTINEL_OPERATOR_TOKEN` using `hmac.compare_digest`. FL clients use a different authentication path (Ed25519 key registration). There is no mechanism for a client to present an operator token — they are issued separately and stored outside the codebase (`~/.finsentinel/dev_token.txt`).

**Q8. Why is the reason field mandatory for approval decisions?**

Audit trails for high-risk financial model changes must be non-repudiable and explain the human judgement. Without a reason the audit event is meaningless for post-incident review. The backend enforces this at the Pydantic layer (`min_length=1`) so it cannot be bypassed by an API client, and the frontend validates it before submitting.

---

## Signatures & Integrity

**Q9. What would happen if a client sent a valid signature over a corrupted payload?**

The pipeline checks SHA-256 integrity before the signature. Wait — actually in FinSentinel the pipeline order is: auth (operator token) → SHA-256 integrity check → signing key lookup → Ed25519 signature verification → schema validation → policy check → replay check. If the SHA-256 digest in the envelope does not match the recomputed digest of the raw bytes, the update is rejected at the integrity stage with a `security.payload_integrity_failed` audit event (rule 100112, level 10, MITRE T1565.002) before signature verification is even attempted.

**Q10. What prevents a client from registering a fake public key for another client's ID?**

Key registration (`POST /register`) requires the operator token. Only an authenticated operator can associate a public key with a client ID. A rogue FL client has no path to register keys.

---

## SIEM / Wazuh Integration

**Q11. Why forward events to Wazuh instead of just logging them locally?**

Local logs have no alerting, no dashboards, and no correlation. Wazuh gives: (1) real-time alerting on severity thresholds — a High event (level 10–12) generates an email/webhook to the SOC immediately; (2) brute-force correlation — rule 100140 fires a Critical (level 13, MITRE T1110) alert when 5 or more signature failures arrive from one client within 60 seconds; (3) MITRE ATT&CK mapping for each rule, so the SOC sees T1553 for key-tampering and T1565 for data manipulation immediately; (4) the Wazuh Discover/Dashboard UI for retrospective investigation without touching the backend.

**Q12. How is the SIEM pipeline secured?**

The delivery worker (`FINSENTINEL_AUDIT_WEBHOOK_TOKEN`) uses HMAC Bearer authentication on the forwarder endpoint. The forwarder validates the token with `hmac.compare_digest` before accepting any event. The forwarder is bound to `127.0.0.1:9999` — it is not reachable from outside the host. All 24 VAPT-generated attack events were confirmed delivered in VAPT run 900be0.

**Q13. Why does the VAPT report show 24 SIEM events when there were more attack tests?**

Not all security events generate a SIEM delivery. Only events that the ingestion pipeline emits as audit records and that the outbox worker successfully delivers to the forwarder are counted. Test categories C1 (auth), C8 (hygiene), C9 (secrets) test HTTP properties without submitting model updates, so they produce no SIEM events. The 24 events correspond to the C3/C4/C6/C7 categories that drive the ingestion pipeline.

---

## Anomaly Detection

**Q14. What statistical anomaly detectors are implemented?**

Six rule-based threshold checks configured via environment variables:
- `FINSENTINEL_MAX_WEIGHT_L2_NORM` — unusually large weight magnitude
- `FINSENTINEL_MAX_UPDATE_L2_NORM` — unusually large update delta
- `FINSENTINEL_MAX_WEIGHT_ABS_MEAN` — mean absolute weight magnitude
- `FINSENTINEL_MAX_WEIGHT_STD` — standard deviation of weights
- `FINSENTINEL_MAX_WEIGHT_ZERO_FRACTION` / `MIN` — sparsity bounds

Any threshold breach sets `suspicious=true` and adds a reason to `anomaly_reasons`. The risk score aggregates breach counts. If risk score exceeds the high-risk threshold the update goes to `pending_approval` (or `quarantined` if configured). Thresholds are currently uncalibrated (requirement S5-10, the only NOT IMPLEMENTED requirement).

---

## VAPT & Security Testing

**Q15. How was the VAPT methodology chosen?**

OWASP API Security Top 10 2023 (API1–API10) is the most widely accepted standard for REST API security assessment. Each category maps to realistic attack patterns against a financial FL gateway: broken authentication, injection, state-machine abuse, rate limiting, SIEM pipeline tampering. The VAPT suite is fully automated and re-runnable (`--dry-run` supported), so it can be run against any new deployment to verify the same controls.

**Q16. What do the 4 FAIL results mean, and how many security findings are there?**

4 FAILs confirm 3 unique gaps (F-01..F-03); 3 additional Low findings (F-04..F-06) were identified from source analysis — giving **6 security findings total**.

Findings from test FAILs:
- **F-01 (C2-01):** No rate limiting or lockout on the operator-token endpoint. 100 wrong tokens submitted with no 429 or SIEM alert.
- **F-02 (C2-03, C10-02):** Failed operator authentication produces no audit record. The 401 is logged in the access log but no SIEM event fires, so brute-force attempts are invisible in Wazuh until rule 100140 fires (which itself requires at least 5 failures).
- **F-03 (C10-03):** Aggregation runs are not audited. No SIEM event for `POST /aggregation/run`.

Source-analysis findings (Low severity, no failing test):
- **F-04:** Schema validation precedes policy checks — policy-rejection events never fire if no schema is registered (fail-secure, but SIEM blind spot in misconfigured deployments).
- **F-05:** `/docs`, `/redoc`, `/openapi.json` accessible without auth — acceptable in dev, reconnaissance risk in production.
- **F-06:** Forwarder deduplication is in-memory only — a forwarder restart during outbox replay could produce duplicate SIEM lines.

All 70 VAPT tests are automated in `scripts/vapt_suite.py` with detailed evidence in `artifacts/vapt_results.json` and `docs/VAPT_REPORT.md`.

**Q17. Why test on localhost only?**

This is a B.Tech project running on a personal laptop; there is no production server. The VAPT scope is explicitly `127.0.0.1` to avoid any accidental external network traffic. The backend is isolated on port `:8001` (separate `vapt.db`) so the test never touches the development data on `:8000`.

---

## Known Gaps & Roadmap

**Q18. What would you fix first in a production deployment?**

In priority order:
1. **F-01:** Add nginx `limit_req` on operator-prefixed paths in production (5 reqs/min with burst 3). This is already in `configs/nginx.conf` as a commented suggestion.
2. **F-02:** Emit `auth.operator_failed` audit event from `api/_auth.py` on every 401, so Wazuh can correlate failed attempts even before 100140 fires.
3. **S5-10:** Calibrate anomaly thresholds on real clean FL update data from a staging run.
4. **F-03:** Audit `POST /aggregation/run` with a `federation.aggregation_triggered` event.

**Q19. Is there a risk of the operator token being leaked?**

The token is stored in `~/.finsentinel/dev_token.txt` (outside the repository). The `.gitignore` excludes `.finsentinel/`. The token is loaded into memory at startup and never written to any response body. The VAPT test C9-01 (`grep` scan for hardcoded secrets) and C9-02 (`git ls-files` scan for tracked sensitive files) both PASS. The frontend never persists the token to `localStorage` — it lives only in React state and is cleared on page refresh.

**Q20. How would this scale to 100 FL clients?**

The bottleneck is the ingestion concurrency cap (`FINSENTINEL_MAX_CONCURRENT_INGESTION`, default 10) and the synchronous outbox delivery worker. At 100 concurrent clients: (a) increase concurrency cap; (b) run multiple delivery worker processes (or switch to Redis Streams); (c) replace SQLite with PostgreSQL (already supported — the project uses PG 18.6 in production mode); (d) add nginx upstream load balancing. The cryptographic pipeline (Ed25519 + SHA-256) adds ~2 ms per update and scales linearly.

**Q21. Why does the operator dashboard Health Monitor show "Degraded"?**

The `outbox.dead_letter_count` is 25 (non-zero), which causes Health Monitor to report **Degraded**.  These 25 events were dead-lettered during an earlier demo run (run ID 37dfac) when the SIEM forwarder was offline and the outbox exhausted all 10 retry attempts.  There is currently no automatic requeue path for dead-lettered events — that is a known roadmap item.  The dead letters do not affect run 900be0 VAPT results or current demo data; they are a persistent artifact of the earlier failed delivery.
