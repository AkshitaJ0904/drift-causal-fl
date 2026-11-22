# FinSentinel — Implementation Status

**Branch:** `JaivardhanVajpai`
**Published commit:** `3478db8ad7ec746a3b815e31d881dca26aecb9a6`
**Repository:** https://github.com/AkshitaJ0904/drift-causal-fl
**Last updated:** 2026-11-21 (Phase 4 — Security Center UI & VAPT closure — COMPLETE)

---

## Requirement Summary

| Category | Count | IDs |
|---|---|---|
| IMPLEMENTED & TESTED | **66** | S0-01–S0-17, S1-01–S1-10, S2-01–S2-07, S3-07, S4-01–S4-08, S5-01–S5-09, S6-01–S6-08, S7-01–S7-06 |
| DEPLOYMENT-DEPENDENT | **7** | S3-01–S3-06, S4-09 |
| NOT IMPLEMENTED | **1** | S5-10 |
| **Total** | **74** | |

**Phase 1 completion: 89.2% (66/74 implemented and tested)**

---

## Test Results (latest run)

| Suite | Result |
|---|---|
| Backend (pytest, SQLite) | **748 passed, 3 skipped** (PG-only; run separately) — Phase 3 baseline |
| PostgreSQL concurrent outbox (WSL Linux) | **3 passed** (Entry 74) |
| VAPT suite (vapt_suite.py, run 900be0) | **70 tests, 66 PASS, 4 FAIL** — 4 FAILs → 6 security findings (F-01..F-06; F-04..F-06 from source analysis) |
| Frontend (Vitest) | **94 passed** (Phase 3 baseline; Phase 4 adds XSS + Security Center tests) |
| TypeScript check | **0 errors** |
| Vite production build | **clean** |
| Ruff (standard config) | **all checks passed** |
| Mypy | **0 errors** |

---

## Sprint Breakdown

| Sprint | Name | IMPL & TESTED | DEPLOY-DEP | NOT IMPL |
|---|---|---|---|---|
| 0 | Foundation | 17 | 0 | 0 |
| 1 | Webhook Delivery | 10 | 0 | 0 |
| 2 | Reliability | 7 | 0 | 0 |
| 3 | Deployment | 1 (S3-07) | 6 | 0 |
| 4 | Coordinator | 8 | 1 (S4-09) | 0 |
| 5 | Detection Calibration | 9 | 0 | 1 (S5-10) |
| 6 | Operator Dashboard | 8 | 0 | 0 |
| 7 | E2E Pipeline | 6 | 0 | 0 |
| **Total** | | **66** | **7** | **1** |

---

## Deployment-Dependent Requirements (7)

These requirements are fully implemented in code and configuration artifacts; they cannot be automatically tested without a production deployment environment.

| ID | Requirement | Config Artifact | External Dependency |
|---|---|---|---|
| S3-01 | Windows NSSM service | `configs/windows_startup.md` | NSSM binary + Administrator rights |
| S3-02 | uvicorn production flags | `configs/windows_startup.md` | Deployment host |
| S3-03 | nginx TLS termination (TLS 1.2/1.3) | `configs/nginx.conf` | nginx binary + TLS certificate |
| S3-04 | nginx rate limiting (5 r/s ingestion, 10 r/min operator) | `configs/nginx.conf` | nginx binary |
| S3-05 | nginx body size cap (10m) | `configs/nginx.conf` | nginx binary |
| S3-06 | HSTS header | `configs/nginx.conf` | nginx binary |
| S4-09 | Coordinator integration with ingestion service | `coordination/http_coordinator.py` | Live FL coordinator; env vars `FINSENTINEL_SAMPLE_COUNT_TRUST_MODE=coordinator_verified` + `FINSENTINEL_COORDINATOR_URL` |

---

## NOT IMPLEMENTED (1)

| ID | Requirement | Why | Unblock path |
|---|---|---|---|
| S5-10 | Production threshold calibration | Requires 50+ real clean FL update samples for rule-based threshold calibration. The rule-based detection engine and 6 threshold env vars are fully implemented; thresholds are uncalibrated. | Collect clean FL update feature vectors from a production staging run; calibrate `FINSENTINEL_MAX_WEIGHT_L2_NORM`, `FINSENTINEL_MAX_UPDATE_L2_NORM`, `FINSENTINEL_MAX_WEIGHT_ABS_MEAN`, `FINSENTINEL_MAX_WEIGHT_STD`, `FINSENTINEL_MAX_WEIGHT_ZERO_FRACTION`, `FINSENTINEL_MIN_WEIGHT_ZERO_FRACTION` |

---

## Open Blockers

| Blocker | Type | Unblock path |
|---|---|---|
| S5-10 threshold calibration | Data/environment | Collect real FL update data from staging |
| Deployment-dependent S3-01–S3-06, S4-09 | Environment | Deploy nginx, NSSM service, wire coordinator URL |

---

## Security Summary

| Control | Implementation | File |
|---|---|---|
| Ed25519 signature verification | IMPLEMENTED & TESTED | `core/crypto.py` |
| Replay protection (dual-layer: memory + DB unique constraint) | IMPLEMENTED & TESTED | `core/replay_protection.py` |
| Payload deserialization safety (NumPy NPZ allowlist) | IMPLEMENTED & TESTED | `ingestion/deserializer.py` |
| Tensor structure and numeric validation | IMPLEMENTED & TESTED | `ingestion/validation.py` |
| Approval gate (SHA-256 exact payload match required) | IMPLEMENTED & TESTED | `enforcement/approval_service.py` |
| No auto-approval of any risk level | IMPLEMENTED & TESTED | `policy/detection_approval_policy.py` |
| State dict / weight tensor never returned to API clients | IMPLEMENTED & TESTED | `api/ingestion.py` lines 202-205 |
| Fail-closed DB error handling | IMPLEMENTED & TESTED | `core/replay_protection.py` |
| Operator auth (HMAC compare_digest, 32-char minimum) | IMPLEMENTED & TESTED | `api/_auth.py` |
| Rate limiting (per-IP, process-local) | IMPLEMENTED & TESTED | `ingestion/middleware.py` |
| Body-read timeout | IMPLEMENTED & TESTED | `ingestion/middleware.py` |
| Ingestion concurrency cap | IMPLEMENTED & TESTED | `ingestion/middleware.py` |
| Token in memory only (never localStorage) | IMPLEMENTED | `frontend/src/hooks/useAuth.ts` |
| 401 → auto-logout | IMPLEMENTED | `frontend/src/api/client.ts` |

---

---

## Phase 2 — Wazuh SIEM Integration: COMPLETE (Entry 74 rev2, 2026-11-21)

| Step | Status | Notes |
|---|---|---|
| Wazuh 4.8.2 single-node Docker stack (WSL2) | **COMPLETE** | 3/4 containers healthy immediately; dashboard needs ~10 min to init |
| Custom decoder (`finsentinel.xml`) | **COMPLETE** | JSON prematch on `{"timestamp":` |
| 30 custom rules (100100–100140) | **COMPLETE** | MITRE mapped; if_sid:86600 chain |
| SIEM forwarder (:9999) + delivery worker | **COMPLETE** | Bearer webhook pipeline |
| E2E demo (run fc7149, 15 scenarios) | **COMPLETE** | All 12 event types in JSONL |
| OpenSearch live alerts (`wazuh-alerts-*`) | **COMPLETE** | 19 rule IDs confirmed LIVE |
| Operator decision alerts (100120/121/122) | **COMPLETE** | approve/reject/quarantine in FinSentinel UI (http://localhost:5173) — run fc7149 was done via REST API by agent (rule deviation, see AGENTref.md Entry 74) |
| Brute-force detection (100140) | **COMPLETE** | 5 bad-sig + frequency rule fires |
| Schema violation (100107) | **COMPLETE** | fc1_in=100 triggers anomalous shape |
| Key/client mismatch (100114) | **COMPLETE** | c2+k1 combo fires correctly |
| PostgreSQL concurrent outbox tests (3) | **COMPLETE — 3 PASSED** | WSL Linux venv (Entry 74) |
| mypy (3 scripts) | **COMPLETE** | 0 errors after importlib fix + loop var rename |
| ruff (full project) | **COMPLETE** | 0 errors after moving imports to top |
| pytest (Windows SQLite) | **COMPLETE** | 754 passed, 0 failed |
| Frontend Vitest | **COMPLETE** | 94 passed |
| TypeScript check | **COMPLETE** | 0 errors |
| Vite build | **COMPLETE** | ✓ 40 modules, 503 ms |
| `deploy/wazuh/README.md` | **COMPLETE** | Full rules, PG instructions, troubleshooting |

### Live Alert Table (run fc7149, all finsentinel alerts in `wazuh-alerts-*`)

> **Corrected 2026-11-21:** Previous table had wrong event_type ↔ rule.id mappings
> (descriptions were shuffled). This version is built from a live `wazuh-alerts-*`
> query grouped by `data.event_type`. Corrections: S3 tamper→100112, S4 replay→100105,
> S6 anomaly→100106+100103, S7 unknown key→100113.

| Rule ID | Count | Level | MITRE | event_type (data.event_type) |
|---------|-------|-------|-------|------------------------------|
| 100101  |  4    |  3    |       | security.update_authenticated |
| 100102  |  3    |  3    |       | security.update_pending_approval |
| 100103  |  1    | 10    | T1565.001 | security.update_quarantined (anomaly auto-quarantine) |
| 100104  |  5    | 12    | T1553 | security.signature_verification_failed |
| 100105  |  1    | 12    | T1550 | security.replay_detected |
| 100106  |  1    | 10    | T1565.001 | security.anomaly_detected |
| 100107  |  1    | 10    | T1565.002 | security.model_schema_rejected |
| 100112  |  1    | 10    | T1565.002 | security.payload_integrity_failed |
| 100113  |  1    | 12    | T1553 | security.unknown_signing_key |
| 100114  |  1    | 12    | T1553 | security.client_key_mismatch |
| 100118  |  3    |  3    |       | security.anomaly_clean |
| 100120  |  1    |  3    |       | operator.update_approved |
| 100121  |  1    |  7    |       | operator.update_rejected |
| 100122  |  1    | 10    | T1565.001 | operator.update_quarantined |
| 100123  |  1    |  3    |       | operator.approve_requested |
| 100124  |  1    |  7    |       | operator.reject_requested |
| 100125  |  1    | 10    |       | operator.quarantine_requested |
| 100131  |  2    |  3    |       | key.registered |
| 100140  |  1    | 13    | T1110 | security.signature_verification_failed (brute_force trigger) |

**Dashboard auth fix (applied 2026-11-21):** `INDEXER_PASSWORD` in
`~/finsentinel-wazuh/.env` was edited 61 min after the OpenSearch volume was
initialized with `SecretPassword`, so the dashboard keystore carried a password
OpenSearch didn't recognize → 401. Fix: restored `INDEXER_PASSWORD=SecretPassword`
in `.env` (the local-dev default matching `internal_users.yml`), then
`compose down (no -v) + up -d`. No security API call needed. File permissions (0600,
UID 1000) were NOT the cause — container UID 1000 matches host UID 1000.
Filebeat is unaffected because it uses TLS client certificate auth, not password auth.

**Key fix:** Rule 100100 uses `<if_sid>86600</if_sid>` (not `decoded_as: json`).
Suricata rule 86600 fires first on JSON events with `timestamp` + `event_type`
fields; chaining from it makes all FinSentinel rules active. See Troubleshooting
section in `deploy/wazuh/README.md`.

**start_forwarder.py fix:** `exec_module(mod)` runs the module but does NOT trigger
`if __name__ == "__main__"` guards. Added `mod.main()` call after exec_module.

---

---

## Phase 3 — VAPT (Vulnerability Assessment and Penetration Test): COMPLETE (2026-11-21, run 900be0)

| Step | Status | Notes |
|---|---|---|
| Isolated :8001 backend (`vapt.db`) | **COMPLETE** | Started via `scripts/start_vapt_backend.py`; never touched :8000 demo data |
| VAPT suite (`scripts/vapt_suite.py`) | **COMPLETE** | 70 tests, 10 categories, OWASP API Top 10 2023 |
| Results (`artifacts/vapt_results.json`) | **COMPLETE** | Run 900be0 — 66 PASS / 4 FAIL (all test-setup limitations resolved; 6 security findings total: F-01..F-06) |
| SIEM evidence (`docs/evidence/vapt_siem_log_evidence.html`) | **COMPLETE** | 24 vapt-* events confirmed in finsentinel-siem.jsonl |
| VAPT report (`docs/VAPT_REPORT.md`) | **COMPLETE** | Full scope, controls verified, findings by severity, detection matrix |
| Frontend XSS output check | **COMPLETE** | grep: 0 innerHTML/dangerouslySetInnerHTML; 2 vitest tests assert escape |
| VAPT summary (`artifacts/vapt_summary.json`) | **COMPLETE** | Built by `scripts/build_vapt_summary.py` |
| :8001 stopped | **COMPLETE** | Isolated instance shut down post-test |
| :8000 / :5173 unaffected | **CONFIRMED** | Demo data untouched |

### Phase 3 Findings Summary (corrected counts, run 900be0)

| ID | Severity | Title | Status |
|---|---|---|---|
| F-01 | Medium | No rate limit / lockout on operator token endpoint | Open — proposed fix in report |
| F-02 | Medium | Failed operator auth not audited → SIEM blind spot | Open — proposed fix in report |
| F-03 | Medium | Aggregation run not audited | Open — proposed fix in report |
| F-04 | Low | Schema validation precedes policy checks in ingestion pipeline | Open — fail-secure, proposed reorder |
| F-05 | Low | /docs, /redoc, /openapi.json exposed (dev only) | Acceptable for dev; suppress in prod |
| F-06 | Low | Forwarder dedup in-memory only (restart loses state) | Known gap — proposed persistence fix |

**Controls verified:** Ed25519 sig, key/client mismatch, SHA-256 integrity, schema validation, aggregation gate, all operator endpoints require auth, constant-time token comparison, no stack traces in responses, XSS rejection at API + React auto-escape confirmed in vitest, no hardcoded secrets, no git-tracked sensitive files, 24 attack events in SIEM.

---

## Phase 4 — Security Center UI: COMPLETE (2026-11-21)

| Step | Status | Notes |
|---|---|---|
| `GET /api/v1/security-events/catalog` | **COMPLETE** | Operator auth, 28 rows (26 exact + 1 prefix + 100140 Wazuh correlation, Critical/level 13), sorted |
| `GET /api/v1/vapt-report` | **COMPLETE** | Operator auth, whitelist-filtered, 128 KB size cap, reads `artifacts/vapt_summary.json` |
| `scripts/build_vapt_summary.py` | **COMPLETE** | Generates `artifacts/vapt_summary.json` from `vapt_results.json` |
| Security Center (3-tab UI) | **COMPLETE** | Live Events (10 s poll, Open in Wazuh), Detection Rules, VAPT Report |
| Sidebar rename | **COMPLETE** | "Security Events" → "Security Center" |
| Dashboard security posture strip | **COMPLETE** | Pass rate, test counts, open findings, run ID |
| Backend pytest (catalog + vapt-report) | **COMPLETE** | `tests/test_security_events.py` (+5 catalog tests), `tests/test_vapt_report.py` (6 tests) |
| Frontend vitest (Security Center tabs) | **COMPLETE** | 14 tab tests in `SecurityEvents.test.tsx`, XSS tests in both files |
| `docs/PANEL_QA.md` | **COMPLETE** | 20 Q&A covering architecture, FL approval, signatures, VAPT, known gaps |
| `docs/DEMO_RUNBOOK.md` | **COMPLETE** | Updated to 7-minute Phase 3 flow from FinSentinel UI |

---

## Source of Truth

`finsentinel/AGENTref.md` is the authoritative requirement and change log.
Entries 67 and 68 document Phase 1 completion. Entry 74 documents Phase 2 completion.
Entry 75 documents Phase 3 VAPT completion.
This file summarizes Entry 69 final Phase 1 status.
