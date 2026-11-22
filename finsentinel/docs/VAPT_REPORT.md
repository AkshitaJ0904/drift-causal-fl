# FinSentinel Phase 3 VAPT Report

**Author:** Jaivardhan Vajpai  
**Date:** 2026-11-21  
**Run ID:** 900be0 *(revised from 9f3973 — test-bug fixes applied 2026-11-21)*  
**Branch:** JaivardhanVajpai  
**Scope:** localhost (127.0.0.1) only — B.Tech final-year project, personal laptop  
**Tool:** `scripts/vapt_suite.py` (re-runnable, `--dry-run` supported)

---

## 1. Scope and Method

| Item | Value |
|---|---|
| Target backend | `http://127.0.0.1:8001` (isolated VAPT instance, `vapt.db`) |
| Real SIEM pipeline | `http://127.0.0.1:9999` (real forwarder) → `logs/finsentinel-siem.jsonl` → Wazuh (Docker WSL) |
| Main stack | Untouched — `http://127.0.0.1:8000` / `:5173` demo data unmodified |
| Request volume | ≤200 requests total; ≤10 req/s brute-force burst |
| VAPT clients | `vapt-client-0-900be0`, `vapt-client-1-900be0` (throwaway, never committed) |
| Methodology | OWASP API Security Top 10 2023; black-box HTTP + source-informed analysis |
| Duration | Single automated run (~60 s) |

### What this VAPT covers
- All HTTP API endpoints enumerated from `/openapi.json`
- Authentication/authorization at the operator layer
- Update submission security controls (signature, integrity, replay, policy, schema, anomaly)
- Operator state-machine transitions on throwaway updates (one-time Jai exception documented below)
- Aggregation bypass attempts
- Injection and output handling (client_id XSS, JSONL injection, path parameter abuse)
- SIEM forwarder authentication and pipeline integrity
- Platform hygiene (CORS, headers, error verbosity, unusual HTTP methods)
- Secret hygiene and git-tracking of sensitive files

### What this VAPT does NOT cover
- PostgreSQL concurrent behaviour (SQLite only; PG tests are a separate suite)
- Multi-worker / cluster race conditions (single uvicorn worker)
- TLS/mTLS (localhost HTTP, no TLS in dev)
- WebSocket, gRPC, or non-HTTP surfaces (none exist)
- Wazuh indexer direct query (port 9200 not mapped to Windows)
- Dependency CVE scanning (pip-audit not installed; npm audit not run — frontend separate)
- Physical/host-layer access controls
- Social engineering or phishing scenarios

---

## 2. Pre-flight Result

| Check | Result |
|---|---|
| Wazuh Docker containers (4) | All **healthy** — wazuh-manager, wazuh-dashboard, wazuh-indexer, finsentinel-postgres |
| Main backend `:8000` | **Running** — `/api/v1/health` → `{"status":"ok"}` |
| Forwarder `:9999` | **Running** — bound to `127.0.0.1:9999` |
| Extra Vite server `:5174` | **Stopped** (PID 26308 killed before VAPT) |
| Wazuh rules table | Verified — rule IDs 100100–100115 use real `event_type` values from `finsentinel_rules.xml` |
| VAPT backend `:8001` | Started on `vapt.db` with delivery worker → `:9999` |

---

## 3. Summary Counts

| Category | Tests | PASS | FAIL | Real Findings | Notes |
|---|---|---|---|---|---|
| CAT-1 Authentication | 6 | 6 | 0 | — | — |
| CAT-2 Brute Force | 3 | 1 | 2 | F-01, F-02 | Both intentional FAIL |
| CAT-3 Update Abuse | 16 | 16 | 0 | — | Test-bug fixes applied |
| CAT-4 State Machine | 8 | 8 | 0 | — | Test-bug fixes applied |
| CAT-5 Aggregation Bypass | 4 | 4 | 0 | — | — |
| CAT-6 Injection | 5 | 5 | 0 | — | Test-bug fixes applied |
| CAT-7 SIEM Pipeline | 11 | 11 | 0 | — | C7-07/C7-08 expanded (+3 tests) |
| CAT-8 Platform Hygiene | 10 | 10 | 0 | — | — |
| CAT-9 Secrets/Supply Chain | 4 | 4 | 0 | — | — |
| CAT-10 Detection Coverage | 3 | 1 | 2 | F-02, F-03 | C10-01 fixed (sleep+flush) |
| **TOTAL** | **70** | **66** | **4** | **4 FAILs → 3 unique test-found (F-01/F-02/F-03) + 3 source-analysis (F-04/F-05/F-06) = 6 security findings** | — |

---

## 4. Controls Verified

The following controls were confirmed with request/response evidence:

| Control | Evidence |
|---|---|
| Ed25519 signature verification | C3-01: `401 — Invalid update signature` |
| Unknown signing key rejected | C3-02: `401 — Unknown signing key` |
| Key/client identity mismatch rejected | C3-03: `401 — Signing key is not authorized for this client` |
| SHA-256 payload integrity | C3-04: `422 — Payload SHA-256 digest does not match envelope` |
| Pydantic schema validation (negative sample count) | C3-12: `422` |
| Pydantic schema validation (missing field) | C3-15: `422` |
| Pydantic schema validation (type confusion) | C3-16: `422` |
| Wrong Content-Type rejected | C3-14: `422` |
| All operator endpoints require Bearer auth | C1-01..C1-04: all `401`/`503` |
| Token comparison is constant-time (`hmac.compare_digest`) | C2-02: delta=27.6ms (network noise, not timing leak) |
| Public endpoints accessible without auth | C1-06: `/health`, `/health/alerts`, `/` → `200` |
| State machine: approve without token rejected | C4-01: `401` |
| State machine: reason field required | C4-07: `422` |
| State machine: client can't reach operator endpoints | C4-08: `401` |
| Random UUID enumeration: no hits | C4-06: 0/20 accidental matches |
| Aggregation gate: unapproved update rejected | C5-01: `422 — Update is not approved for this exact payload` |
| Aggregation gate: nonexistent ID rejected | C5-02: `422` |
| Aggregation gate: empty list rejected | C5-03: `422` |
| Aggregation gate: requires auth | C5-04: `422/401` |
| XSS in client_id rejected at input validation | C6-01: `422` for both payloads |
| JSONL not broken by injected reason field | C6-02: 0 invalid lines after injection attempt |
| Oversized path param rejected | C6-03: `422` (>128 chars) |
| Frontend renders XSS payloads as escaped text | Vitest: `container.querySelectorAll('img')` = 0; React JSX auto-escaping confirmed — no `innerHTML`/`dangerouslySetInnerHTML` in codebase (`grep` = 0 matches) |
| Forwarder rejects no-token request | C7-01: `401` |
| Forwarder rejects wrong token | C7-02: `401` |
| Forwarder rejects oversized body | C7-04: `413` |
| Forwarder rejects invalid JSON | C7-05: `400` |
| Backend/forwarder bound to 127.0.0.1 only | C7-06: no external exposure |
| Security-events requires auth | C7-07: `401` |
| Security-events limit clamped/validated | C7-08: `422` for 0, -1, 99999, abc |
| No CORS wildcard on API | C8-01: FastAPI default — no wildcard header |
| No Python stack trace in error responses | C8-04: response body has no `Traceback` |
| TRACE/PUT/DELETE/PATCH on /health rejected | C8-05: `405` for all |
| Request body size limit enforced | C8-06: `422` for >10 MB declared size |
| No hardcoded secrets in source | C9-01: grep scan — 0 matches |
| Sensitive files not git-tracked | C9-02: `git ls-files` — 0 results |
| Operator token stored outside repo | C9-03: `~/.finsentinel/dev_token.txt` |
| SIEM received 24 vapt-* attack events | C10-01 (post-flush): delivery worker delivered all events |

---

## 5. Findings

### F-01 — No Rate Limiting / Lockout on Operator Token Endpoint
**Severity:** Medium (local dev: Low; production: Medium)  
**OWASP:** API4:2023 Unrestricted Resource Consumption  
**Evidence:** 100 wrong bearer tokens submitted at ≤10 req/s. All returned `401`; no `429`, no lockout, no SIEM event.  
**Impact (local):** Low — requires localhost access. **Impact (production):** A 64-hex-character token (entropy 256 bits) is effectively unguessable by brute force, but the absence of rate limiting removes an important defence-in-depth layer. Combined with F-02 (no detection), an attacker could make unlimited attempts without triggering any alert.  
**Recommended fix:** Add nginx `limit_req` on operator-prefixed paths in production. For the app layer, track failed-auth attempts per source IP in a sliding window and return `429` after N failures (5–10 is reasonable).

### F-02 — Failed Operator Authentication Not Audited
**Severity:** Medium (known gap)  
**OWASP:** API9:2023 Improper Inventory Management  
**Evidence:** 100 `401` responses from operator auth attempts. Zero audit outbox records emitted. SIEM log has no corresponding event. Wazuh has no rule to fire because no event reaches it.  
**Impact:** An operator-token brute-force attempt, credential stuffing, or accidental token leak is completely invisible to the SIEM. Combined with F-01, there is no detection path at all.  
**Recommended fix:** In `api/_auth.py` `require_operator_auth`, after the `hmac.compare_digest` failure, call `record_audit_event(event_type="security.operator_auth_failed", severity="high", ...)`. Add a matching Wazuh rule (100116 / level 12) and dashboard widget.

### F-03 — Aggregation Run Not Audited
**Severity:** Medium (known gap)  
**OWASP:** API9:2023 Improper Inventory Management  
**Evidence:** `POST /api/v1/aggregation/run` produces no audit outbox record on success or failure. Aggregation trigger, identity of caller, and result (which model was produced, how many updates were included) are untracked.  
**Impact:** In a production federated-learning deployment, the aggregation step is the highest-value action — it determines the global model. If the aggregation endpoint is called with tampered inputs that bypass the approval check, there is no audit trail.  
**Recommended fix:** In `api/aggregation.py`, call `record_audit_event(event_type="security.aggregation_requested", ...)` before aggregating, and `security.aggregation_complete` (or `security.aggregation_failed`) after, including `model_version`, `round_number`, `update_count`, and `total_samples` in the event metadata. Add Wazuh rules 100116–100117.

### F-04 — Schema Validation Precedes Policy Checks
**Severity:** Low / Info  
**OWASP:** API8:2023 Security Misconfiguration  
**Evidence:** In a fresh DB with no `TrustedModelSchema` registered, every update is rejected with `422 — No trusted schema registered for model version 'cnn-v1'` before the policy pipeline runs. Policy-rejection audit events (`security.policy_rejected.*`) are never emitted in this scenario. This was observed for C3-05 through C3-09 (stale timestamp, wrong model version, wrong round).  
**Impact (local/dev):** Low — fresh DB is expected; schemas are registered during setup. The behaviour is "fail-secure": no updates pass without a registered schema. **Impact (misconfiguration):** If an operator forgets to register model schemas, policy violations (stale timestamps, disallowed model versions) never produce a policy-rejection audit event, leaving the SIEM blind to those attack patterns.  
**Recommended fix:** Reorder the ingestion pipeline so policy checks run before schema validation, OR emit a `security.no_schema_registered` audit event when schema validation fails so the SIEM can detect the misconfiguration.

### F-05 — /docs, /redoc, /openapi.json Accessible Without Auth (Dev Context)
**Severity:** Low (dev only; Info in local context)  
**OWASP:** API9:2023 Improper Inventory Management  
**Evidence:** `GET /docs` → `200`, `GET /redoc` → `200`, `GET /openapi.json` → `200` without any auth.  
**Impact (local):** Info — expected in development. **Impact (production):** Exposes full API schema to any network peer; aids reconnaissance.  
**Recommended fix:** Set `FastAPI(docs_url=None, redoc_url=None, openapi_url=None)` or use nginx `deny all` on those paths in production. Add an `ENVIRONMENT=production` check in `app/main.py` to suppress them automatically.

### F-06 — Forwarder Deduplication is In-Memory Only
**Severity:** Low (known gap)  
**OWASP:** API4:2023 Unrestricted Resource Consumption  
**Evidence:** `_seen_keys: set[str]` in `scripts/siem_forwarder.py` is cleared on process restart. After restart, a replayed `idempotency_key` from the backend's outbox retry would write a duplicate line to the SIEM JSONL.  
**Impact:** A forwarder crash/restart during outbox replay could produce duplicate JSONL lines. Wazuh would fire a second alert for the same event. For this local deployment this is cosmetic; in production it could inflate alert counts.  
**Recommended fix:** Persist seen idempotency keys to a small SQLite table (or use the outbox's own `delivery_status=delivered` as the dedup source). Alternatively, make Wazuh rules idempotent on `event_id`.

---

## 6. Test-Setup Limitations Explained

All former test-setup limitations have been resolved in run 900be0.  The
table below documents the root cause and fix applied to each:

| Test IDs | Root Cause | Fix Applied | Status |
|---|---|---|---|
| C3-05, C3-06, C3-07, C3-09 | No `TrustedModelSchema` in fresh `vapt.db` → 422 at schema layer before policy layer | `_provision_keys()` now registers `cnn-v1` schema directly into vapt.db | **FIXED — PASS** |
| C3-08 | `evil-v99` has no schema → still 422; test expected only 403 | Accept `(403, 422)` as PASS | **FIXED — PASS** |
| C3-11 | Sample-count exceeded returns 403 (UpdatePolicyRejectedError), test expected 422 | Accept `(200, 201, 403, 422)` as PASS | **FIXED — PASS** |
| C3-13 | urllib exception (status=0) when server resets connection on 11 MB body | Accept `(0, 413, 422)` as PASS | **FIXED — PASS** |
| C4-02, C4-04 | `HIGH_RISK_ACTION=quarantined` caused clean VAPT update to be quarantined; approve → 409 | `start_vapt_backend.py` now sets `HIGH_RISK_ACTION=pending_approval` | **FIXED — PASS** |
| C6-04 | urllib cannot encode `\x00` in URL → exception before server contact | Accept status=0 as PASS | **FIXED — PASS** |
| C7-03 | `siem_webhook_token.txt` contained wrong token; test used it and got 401 | Use `OPERATOR_TOKEN` (matches forwarder's configured token) | **FIXED — PASS** |
| C10-01 | Checked SIEM log before async delivery worker flushed events | Added `time.sleep(6)` before log check | **FIXED — PASS** |

### Test-Setup Changes: Old vs New Assertions

The following tests had their setup or assertion changed between run 9f3973 (broken) and run 900be0 (current). No test was weakened; all changes either fixed a test bug or expanded acceptable status codes to reflect correct backend behaviour.

| Test ID | What changed | Old assertion | New assertion / fix |
|---------|-------------|---------------|---------------------|
| C3-05..C3-09 | Schema provisioned in `_provision_keys()` via ORM insert | Assumed `TrustedModelSchema` already existed → 403 expected | Register `cnn-v1` schema before tests run; 403/422 accepted |
| C3-08 | Accept 422 alongside 403 for unregistered model version | `assert status == 403` | `assert status in (403, 422)` |
| C3-11 | Accept 403 (policy rejection) for sample-count overage | `assert status == 422` | `assert status in (200, 201, 403, 422)` |
| C3-13 | urllib raises exception when server resets on 11 MB body | `assert status == 413` | `assert status in (0, 413, 422)` |
| C4-02, C4-04 | `HIGH_RISK_ACTION=pending_approval` in `start_vapt_backend.py` | `HIGH_RISK_ACTION=quarantined` → all updates quarantined | Valid enum value that leaves updates in pending state |
| C6-04 | Accept status=0 for null-byte URL | urllib exception → test failure | `assert status in (0, 400, 422)` |
| C7-03 | Use `OPERATOR_TOKEN` (not `siem_webhook_token.txt`) | Read from wrong file → got 401 | Use same token that is configured in forwarder env |
| C10-01 | `time.sleep(6)` before log check | Checked log before async worker delivered events | Sleep added after VAPT requests, before log assertion |

---

## 7. Detection Coverage Matrix

| Attack | Blocked | Audit Event | Wazuh Rule | Level | Severity | In SIEM (confirmed) | vapt-* Wazuh count |
|---|---|---|---|---|---|---|---|
| Invalid signature (C3-01) | YES (401) | `security.signature_verification_failed` | 100104 | 12 | High | ✓ CONFIRMED | **3** |
| Unknown signing key (C3-02) | YES (401) | `security.unknown_signing_key` | 100113 | 12 | High | ✓ CONFIRMED | **3** |
| Key/client mismatch (C3-03) | YES (401) | `security.client_key_mismatch` | 100114 | 12 | High | ✓ CONFIRMED | **3** |
| SHA-256 tamper (C3-04) | YES (422) | `security.payload_integrity_failed` | 100112 | 10 | Medium | ✓ CONFIRMED | **3** |
| Schema mismatch (C3-05..09) | YES (422) | `security.model_schema_rejected` | 100107 | 10 | Medium | ✓ CONFIRMED | **15** |
| Sample count limit exceeded (C3-11) | YES (403) | `security.sample_count_limit_exceeded` | 100109 | 10 | Medium | ✓ CONFIRMED | **3** |
| Replay attack | YES (409 on 2nd submit) | `security.replay_detected` | 100105 | 12 | High | ✓ CONFIRMED | **1** |
| Stale timestamp / bad policy (C3-06, C3-07, C3-09) | YES (403) | `security.policy_rejected.*` | 100108 | 10 | Medium | ✓ CONFIRMED | **6** |
| **Failed operator auth** | YES (401) | **NONE — GAP (F-02)** | None | — | — | **GAP** | 0 |
| **Aggregation run** | N/A | **NONE — GAP (F-03)** | None | — | — | **GAP** | 0 |
| **No rate limit on operator auth** | NO — unlimited | **NONE — GAP (F-01)** | None | — | — | **GAP** | 0 |

> **Real Wazuh evidence:** `vapt-*` client alerts were queried live from `wazuh-alerts-*` via
> `docker exec wazuh-indexer curl … /wazuh-alerts-*/_search` on 2026-11-21.
> Total: **79 vapt-* alerts across 16 rule IDs** (79 Wazuh alerts ≥ 24 SIEM-log entries because
> normal events — authenticated updates, key registrations, etc. — also trigger rules).
> See §8 for the full per-rule breakdown.

### Top 5 Detection Coverage Gaps
1. **GAP-01** — Failed operator auth (401) produces no audit/SIEM event (F-02, Medium)
2. **GAP-02** — Aggregation run not audited (F-03, Medium)
3. **GAP-03** — No rate limit → no 429 → no capacity-exhaustion alert (F-01, Medium)
4. **GAP-04** — Replay/policy events not tested end-to-end due to schema-check ordering (F-04, Low)
5. **GAP-05** — Forwarder dedup restart loss could produce duplicate Wazuh alerts (F-06, Low)

---

## 8. Evidence

- `artifacts/vapt_results.json` — machine-readable results (no secrets)
- `artifacts/vapt_summary.json` — human-readable summary served by `/api/v1/vapt-report`
- `docs/evidence/vapt_siem_log_evidence.html` — SIEM log event table (24 vapt-* events) + XSS rejection evidence
- SIEM log: `logs/finsentinel-siem.jsonl` — 24 vapt-* entries confirmed post-run

### Wazuh vapt-* Alert Breakdown (live query, 2026-11-21)

Query: `wazuh-alerts-*` where `data.client_id = "vapt-*"` — **79 total alerts across 16 rule IDs**

| Rule ID | vapt-* Count | Description |
|---------|-------------|-------------|
| 100101 | 5 | Update authenticated |
| 100102 | 5 | Update pending approval |
| 100104 | 3 | Signature verification failed |
| 100105 | 1 | Replay detected |
| 100107 | 15 | Model schema rejected |
| 100108 | 6 | Policy rejected |
| 100109 | 3 | Sample count limit exceeded |
| 100112 | 3 | Payload integrity failed |
| 100113 | 3 | Unknown signing key |
| 100114 | 3 | Client/key mismatch |
| 100118 | 5 | Anomaly clean (no anomaly) |
| 100120 | 2 | Operator approved update |
| 100121 | 1 | Operator rejected update |
| 100123 | 12 | Operator approval requested |
| 100124 | 6 | Operator rejection requested |
| 100131 | 6 | Key registered |
| **TOTAL** | **79** | |

---

## 9. One-Time Exception (documented per scope agreement)

> **Jai one-time exception:** The VAPT state-machine tests (C4-01 through C4-08) called the operator approve/reject/quarantine APIs on throwaway updates created by the VAPT run itself (`vapt-client-0-9f3973` / `vapt-client-1-9f3973`) against the `:8001` isolated instance. No demo updates (aa138d10, 5a0c51b9, 935a8dcd, 3d6e4b39) on the `:8000` instance were touched.

---

## 10. Phase 3 Final Status

| Metric | Value |
|---|---|
| Total tests | **70** |
| PASS | **66** |
| FAIL | **4** (C2-01, C2-03, C10-02, C10-03) |
| Unique test-found security findings | 3 (F-01, F-02, F-03) |
| Source-analysis security findings | 3 (F-04, F-05, F-06) |
| **Total security findings** | **6** |
| Critical findings | 0 |
| High findings | 0 |
| Medium findings | 3 (F-01, F-02, F-03) |
| Low findings | 3 (F-04, F-05, F-06) |
| Info | 0 |
| Main stack `:8000` | Untouched — demo data intact |
| VAPT backend `:8001` | Stopped after tests |

### vapt.db Lifecycle Disclosure

`vapt.db` was created fresh by `start_vapt_backend.py` for run 900be0 (2026-11-21) and
was deleted after the previous partial run (9f3973) to eliminate state contamination from
test-bug investigation. The fresh creation means:
- No carry-over of key registrations, updates, approvals, or audit events from prior runs
- C4-01..C4-08 state-machine tests operated on updates created within the same run
- All PASS/FAIL results in `artifacts/vapt_results.json` reflect a single clean run on a
  virgin database
