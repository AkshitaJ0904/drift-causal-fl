# FinSentinel Requirement Matrix

Status codes:
- **IMPLEMENTED** — code exists and runs in production mode
- **TESTED** — covered by at least one automated test
- **DEPLOYMENT-DEPENDENT** — requires operator configuration to activate
- **PARTIALLY** — partial implementation; known gaps documented

---

## Sprint 0 — Foundation (Entry 43 / Sprint 0 baseline)

| Requirement | Status | Evidence |
|---|---|---|
| Ed25519 signature verification | IMPLEMENTED & TESTED | `core/crypto.py`, `test_ingestion_api.py` |
| Replay protection (atomic reservation) | IMPLEMENTED & TESTED | `core/replay_protection.py`, `test_durable_replay_protection.py` |
| Model version policy | IMPLEMENTED & TESTED | `policy/model_update_policy.py`, `FINSENTINEL_ALLOWED_MODEL_VERSIONS` |
| Training-round policy | IMPLEMENTED & TESTED | `policy/model_update_policy.py`, `FINSENTINEL_ALLOWED_ROUNDS` |
| Timestamp freshness policy | IMPLEMENTED & TESTED | `created_at` checked against `FINSENTINEL_MAX_UPDATE_AGE_SECONDS` |
| Payload SHA-256 integrity | IMPLEMENTED & TESTED | `ingestion/payload.py`, `test_payload.py` |
| Schema validation | IMPLEMENTED & TESTED | `core/model_registry.py`, `test_model_registry.py` |
| Anomaly detection (rule-based) | IMPLEMENTED & TESTED | `detection/rule_based.py`, `test_detection_*.py` |
| Approval workflow | IMPLEMENTED & TESTED | `enforcement/approval_service.py`, `api/approval.py` |
| FedAvg aggregation | IMPLEMENTED & TESTED | `aggregation/fedavg.py`, `api/aggregation.py` |
| Transactional audit outbox | IMPLEMENTED & TESTED | `audit/outbox.py`, `test_audit_outbox.py` |
| Sample count trust modes | IMPLEMENTED & TESTED | `ingestion/service.py`, `FINSENTINEL_SAMPLE_COUNT_TRUST_MODE` |
| Concurrency cap (per-process) | IMPLEMENTED & TESTED | `core/concurrency.py`, `FINSENTINEL_MAX_CONCURRENT_INGESTION` |
| Rate limit (per-IP, per-process) | IMPLEMENTED & TESTED | `core/rate_limit.py`, `FINSENTINEL_INGESTION_RATE_LIMIT_RPM` |
| Body-read timeout | IMPLEMENTED & TESTED | `core/middleware.py`, `FINSENTINEL_BODY_READ_TIMEOUT_SECONDS` |
| Operator auth (`require_operator_auth`) | IMPLEMENTED & TESTED | `api/_auth.py`, `FINSENTINEL_OPERATOR_TOKEN` |
| PostgreSQL + Alembic migrations | IMPLEMENTED & TESTED | `alembic/`, `test_postgres_outbox_concurrent.py` |

---

## Sprint 1 — Secure Webhook Delivery

| Requirement | Status | Evidence |
|---|---|---|
| SSRF-safe URL validation | IMPLEMENTED & TESTED | `audit/delivery.py::_validate_delivery_url`, `test_audit_delivery.py::test_loopback_*` |
| Bearer-token auth header | IMPLEMENTED & TESTED | `create_webhook_delivery_fn(token=...)`, `test_audit_delivery.py::test_auth_header_sent` |
| HTTP 2xx success path | IMPLEMENTED & TESTED | `test_audit_delivery.py::test_delivery_succeeds_on_2xx` |
| HTTP 4xx → permanent error (dead-letter) | IMPLEMENTED & TESTED | `DeliveryPermanentError`, `test_audit_delivery.py::test_permanent_error_dead_letters_via_deliver_pending_events` |
| HTTP 5xx / network error → backoff | IMPLEMENTED & TESTED | `test_audit_delivery.py::test_transient_error_applies_backoff_via_deliver_pending_events` |
| Idempotency key stable across retries | IMPLEMENTED & TESTED | `test_audit_delivery.py::test_idempotency_key_stable_across_retries` |
| Three-phase delivery (no DB lock during I/O) | IMPLEMENTED & TESTED | `audit/outbox.py::deliver_pending_events`, `test_audit_delivery.py` |
| `mark_delivered` failure → fallback release | IMPLEMENTED & TESTED | `test_audit_delivery.py::test_delivery_succeeds_mark_delivered_fails_record_retried` |
| Payload schema extension (schema_version, service, event_id) | IMPLEMENTED & TESTED | `audit/outbox.py::_build_payload`, `test_audit_outbox.py` |
| httpx2 removed, canonical httpx used | IMPLEMENTED & TESTED | `requirements.lock`, `coordination/http_coordinator.py`, `test_requirement_evidence.py` |

---

## Sprint 2 — Reliability Hardening

| Requirement | Status | Evidence |
|---|---|---|
| `dead_letter_count()` accuracy | IMPLEMENTED & TESTED | `test_sprint2_reliability.py::test_dead_letter_count_accurate` |
| Claim TTL expiry re-delivers record | IMPLEMENTED & TESTED | `test_sprint2_reliability.py::test_expired_claimed_record_becomes_reclaimable` |
| Worker survives DB outage | IMPLEMENTED & TESTED | `test_sprint2_reliability.py::test_worker_survives_deliver_pending_events_exception` |
| Worker `stop()` clean during idle sleep | IMPLEMENTED & TESTED | `test_sprint2_reliability.py::test_worker_stop_is_clean` |
| Partial batch correct counts | IMPLEMENTED & TESTED | `test_sprint2_reliability.py::test_partial_batch_mixed_outcomes` |
| Dead-letter ERROR log path | IMPLEMENTED & TESTED | `audit/worker.py::_run`, `test_sprint2_reliability.py::test_worker_logs_error_on_dead_letter` |
| Multiple batches drain queue | IMPLEMENTED & TESTED | `test_sprint2_reliability.py::test_multiple_batches_drain_queue` |

---

## Sprint 3 — Deployment Hardening

| Requirement | Status | Evidence |
|---|---|---|
| Windows NSSM service configuration | DEPLOYMENT-DEPENDENT | `configs/windows_startup.md` |
| uvicorn production flags | DEPLOYMENT-DEPENDENT | `configs/windows_startup.md` |
| nginx TLS termination | DEPLOYMENT-DEPENDENT | `configs/nginx.conf` |
| nginx rate limiting | DEPLOYMENT-DEPENDENT | `configs/nginx.conf::limit_req_zone` |
| nginx body size cap | DEPLOYMENT-DEPENDENT | `configs/nginx.conf::client_max_body_size 10m` |
| HSTS header | DEPLOYMENT-DEPENDENT | `configs/nginx.conf::add_header Strict-Transport-Security` |
| Startup security checklist | IMPLEMENTED & TESTED | `configs/windows_startup.md`, `test_requirement_evidence.py` |

---

## Sprint 4 — HTTP Coordinator Adapter

| Requirement | Status | Evidence |
|---|---|---|
| `HttpCoordinatorAdapter` protocol implementation | IMPLEMENTED & TESTED | `coordination/http_coordinator.py`, `test_http_coordinator.py` |
| SSRF guard on coordinator URL | IMPLEMENTED & TESTED | `_validate_coordinator_url`, `test_http_coordinator.py::test_*_url_*` |
| `get_expected_sample_count` | IMPLEMENTED & TESTED | `test_http_coordinator.py::test_get_expected_sample_count_*` |
| `is_client_selected` | IMPLEMENTED & TESTED | `test_http_coordinator.py::test_is_client_selected_*` |
| Thread safety | IMPLEMENTED & TESTED | `coordination/http_coordinator.py`, `test_requirement_evidence.py` |
| Graceful degradation on network error | IMPLEMENTED & TESTED | Returns `None`, `test_http_coordinator.py::test_*_network_error` |
| Bounded timeout | IMPLEMENTED & TESTED | `coordination/http_coordinator.py::_DEFAULT_TIMEOUT`, `test_requirement_evidence.py` |
| `CoordinatorBackedSampleCountProvider` | IMPLEMENTED & TESTED | `test_http_coordinator.py::test_coordinator_backed_provider_*` |
| Coordinator integration with ingestion service | DEPLOYMENT-DEPENDENT | Requires `FINSENTINEL_SAMPLE_COUNT_TRUST_MODE=coordinator_verified` + `FINSENTINEL_COORDINATOR_URL` |

---

## Sprint 5 — Detection Calibration

| Requirement | Status | Evidence |
|---|---|---|
| Harness runs with zero assertion failures | TESTED | `test_sprint5_detection_calibration.py::test_harness_has_no_assertion_failures` |
| Zero scenario errors | TESTED | `test_sprint5_detection_calibration.py::test_harness_has_no_scenario_errors` |
| Clean scenarios: no false positives (loose threshold) | TESTED | `test_sprint5_detection_calibration.py::test_clean_scenarios_no_false_positives_under_l2_loose` |
| Attack scenarios: detected (tight threshold) | TESTED | `test_sprint5_detection_calibration.py::test_attack_scenarios_detected_under_l2_tight` |
| Risk score formula (25 per rule, capped at 100) | IMPLEMENTED & TESTED | `detection/rule_based.py`, `test_sprint5_*::test_risk_score_*` |
| Reason strings contain observed value | IMPLEMENTED & TESTED | `test_sprint5_*::test_reasons_contain_observed_and_threshold` |
| All scenario labels valid | TESTED | `test_sprint5_*::test_scenarios_have_valid_labels` |
| THRESHOLD_CONFIGS covers all rules | TESTED | `test_sprint5_*::test_threshold_configs_cover_all_rules` |
| Dataset inventory documented | IMPLEMENTED & TESTED | `configs/detection_dataset_inventory.md`, `test_requirement_evidence.py` |
| Production threshold calibration | NOT IMPLEMENTED | Requires real clean/attack FL update data |

---

## Sprint 6 — Operator Dashboard

| Requirement | Status | Evidence |
|---|---|---|
| Dashboard authentication (401/503) | IMPLEMENTED & TESTED | `api/_auth.py`, `test_sprint6_dashboard.py::test_dashboard_no_auth_*` |
| `outbox` section (pending_count, dead_letter_count, alert) | IMPLEMENTED & TESTED | `api/dashboard.py`, `test_sprint6_dashboard.py` |
| `registries` section | IMPLEMENTED & TESTED | `api/dashboard.py`, `test_sprint6_dashboard.py::test_dashboard_registries_*` |
| `approvals` section | IMPLEMENTED & TESTED | `api/dashboard.py` |
| `worker` section | IMPLEMENTED & TESTED | `api/dashboard.py`, `test_sprint6_dashboard.py::test_dashboard_worker_*` |
| `config` section | IMPLEMENTED & TESTED | `api/dashboard.py` |
| No token value in response | IMPLEMENTED & TESTED | `test_sprint6_dashboard.py::test_dashboard_config_section_no_token_in_response` |
| `outbox.alert=True` on dead letters | IMPLEMENTED & TESTED | `test_sprint6_dashboard.py::test_dashboard_outbox_alert_true_when_dead_letters_exist` |

---

## Sprint 7 — End-to-End Pipeline Integration

| Requirement | Status | Evidence |
|---|---|---|
| Valid ingestion creates outbox record | TESTED | `test_sprint7_e2e_pipeline.py::test_valid_ingestion_creates_outbox_record` |
| Outbox record deliverable | TESTED | `test_sprint7_e2e_pipeline.py::test_valid_ingestion_outbox_record_is_deliverable` |
| Multiple events delivered in one pass | TESTED | `test_sprint7_e2e_pipeline.py::test_multiple_ingestion_events_delivered_in_one_pass` |
| Dashboard reflects outbox state changes | TESTED | `test_sprint7_e2e_pipeline.py::test_dashboard_reflects_pending_then_delivered` |
| Dashboard alerts on dead-letter | TESTED | `test_sprint7_e2e_pipeline.py::test_dashboard_alerts_on_dead_letter` |
| Full pipeline: ingest → outbox → deliver → dashboard | TESTED | `test_sprint7_e2e_pipeline.py` (all 5 tests together) |

---

## Summary

| Sprint | Implemented | Tested | Deployment-Dependent | Partially/Not Implemented |
|---|---|---|---|---|
| 0 (Foundation) | 17 | 17 | 0 | 0 |
| 1 (Webhook Delivery) | 10 | 10 | 0 | 0 |
| 2 (Reliability) | 7 | 7 | 0 | 0 |
| 3 (Deployment) | 1 | 1 | 6 | 0 |
| 4 (Coordinator) | 8 | 8 | 1 | 0 |
| 5 (Detection Cal.) | 8 | 8 | 0 | 1 |
| 6 (Dashboard) | 8 | 8 | 0 | 0 |
| 7 (E2E Pipeline) | 0 | 6 | 0 | 0 |

**Total: 748 backend tests pass (3 skipped, PostgreSQL-only); 751 pass with `FINSENTINEL_POSTGRES_TEST=1`. 94 frontend tests pass (10 test files).
All core security requirements implemented. Production deployment requires Sprint 3 configuration steps.
Verified Entry 63 (2026-11-19): ruff clean, mypy 0 errors / 148 files, tsc 0 errors, vite build clean. 9 dashboard pages browser-verified at 1440px and 1280px.
Requirement accounting (Entry 67): 66 IMPLEMENTED & TESTED + 0 IMPLEMENTED (S1-10, S3-07, S4-05, S4-07, S5-09 now tested via test_requirement_evidence.py) + 7 DEPLOYMENT-DEPENDENT (S3-01–S3-06, S4-09) + 0 PARTIALLY + 1 NOT IMPLEMENTED (S5-10) = 74 total.
Test count update (Entry 68): 748 backend tests (was 747 — +1 Type A lock acquisition test for S4-05 added to test_requirement_evidence.py).**
