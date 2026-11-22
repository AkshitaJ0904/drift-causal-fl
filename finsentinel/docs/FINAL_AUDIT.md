# FinSentinel — Final Feature Audit

Generated 2026-11-22. Covers Phase 1 (security controls), Phase 2 (audit/SIEM), Phase 3 (VAPT), Phase 7 (UI polish).

| Feature | Where to see it in the UI | Verified by |
|---------|--------------------------|-------------|
| Ed25519 signature verification | Security Center → Detection Rules, rule 100104 | pytest `test_signature_verification_failed`; VAPT F-04 |
| Client-key mismatch detection | Security Center → Detection Rules, rule 100114 | pytest `test_client_key_mismatch` |
| Replay / nonce protection | Security Center → Detection Rules, rule 100105 | pytest `test_replay_detected` |
| SHA-256 payload integrity | Security Center → Detection Rules, rule 100112 | pytest `test_payload_integrity_failed` |
| Pydantic schema validation | Security Center → Detection Rules, rule 100107 | pytest `test_model_schema_rejected` |
| Anomaly scoring (rule-based) | Approvals page → Risk badge; Detection Config thresholds | pytest `test_anomaly_score_applied` |
| Approval gate with audit trail | Approvals page → Approve/Reject/Quarantine, mandatory reason | pytest `test_approval_requires_reason`; check_stack.py /api/v1/updates/pending |
| Audit outbox (SIEM delivery) | Audit Outbox page → Pending Events, Dead-lettered counts | check_stack.py outbox.pending_count; VAPT delivery test |
| Dead-letter recovery | Audit Outbox page → Dead-letter Recovery card | check_stack.py outbox.dead_letter_count |
| Trusted key registry | Trusted Keys page → key list and rule descriptions | check_stack.py /api/v1/trusted-keys |
| Model schema registry | Model Schemas page → schema list | check_stack.py /api/v1/schemas |
| Wazuh SIEM integration (30 rules) | Security Center → Detection Rules (28 rows + brute-force) | Wazuh Security Events dashboard; pytest `test_mapping_matches_rules_xml` |
| Brute-force operator-auth detection | Security Center → Detection Rules, rule 100140 | Wazuh correlation rule; check_stack.py /api/v1/security-events |
| VAPT suite (67 tests) | Security Center → VAPT Report tab | `python scripts/vapt_suite.py`; check_stack.py /api/v1/vapt-report |
| Rate-limit middleware | Health Monitor → Configuration card | pytest `test_rate_limit_applied`; check_stack.py /api/v1/health |
| Body-size limit (10 MB) | — (gateway-level; no UI) | pytest `test_body_size_limit_enforced` |
| Light theme / visual redesign | All pages | vite build; manual review |
| Expandable event rows + filter chips | Security Center → Live Events | vitest `SecurityCenter — expandable rows`; vitest `SecurityCenter — filter chips` |
| Expandable approval rows | Approvals page → click any row | vitest (Phase 7 item 1) |
| Expandable detection rules | Security Center → Detection Rules → click any row | vitest `DetectionRules — expandable` |
| `<Explain>` info icons on KPIs | Overview (Outbox Pending, Dead-lettered); Audit Outbox; Health Monitor; Detection | vitest `Explain component` |
| Glossary (15 terms) | Any Explain ? popover | vitest `Glossary coverage` |
| Dashboard story strip | Overview → "How FinSentinel works" | manual review |
| HOW_TO_LOGIN.md | docs/HOW_TO_LOGIN.md | — |
| THREAT_MODEL_AND_COMPLIANCE.md | docs/THREAT_MODEL_AND_COMPLIANCE.md | — |

## Known Gaps (not defects — documented)

- Isolation Forest (Layer 2) is defined in Detection Config UI but not wired into ingestion.
- Aggregation endpoint does not emit a security event (F-03).
- Failed operator-auth attempts are not written to the SIEM outbox (F-02).
- No per-operator rate limit on approval endpoints (F-01).
- Approvals page expandable rows built in Phase 7; Approvals vitest added this phase.
