# FinSentinel — Incident Response Runbook

This runbook covers the 13 operational scenarios most likely to require immediate
operator action. Each scenario lists detection signals, operator steps, relevant
commands, verification, escalation conditions, and what NOT to do.

All PowerShell commands assume the `venv-security` virtualenv is active and the
working directory is `finsentinel/`.

---

## Scenario 1 — Unauthorized Update Submission (suspected client compromise)

**Detection signals:**
- Approval queue contains a record with `risk_score ≥ 50` and `risk_severity = critical`
- `suspicious = true` on the approval record
- `anomaly_reasons` lists multiple triggered rules

**Operator action:**
1. Open the Approvals page in the operator dashboard.
2. Review the client ID and model version. Cross-reference with known client roster.
3. **Quarantine** the update (do not reject yet — quarantine preserves the record for investigation).
4. Note the `update_id` and `client_id` for the investigation trail.
5. Rotate the client's trusted key if the client is confirmed compromised (see Scenario 10).

**Commands:**
```powershell
# View pending approvals from CLI
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/updates/pending

# Quarantine an update
curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" `
  -d '{"reason": "Suspected model poisoning — elevated L2 norm and zero fraction"}' `
  http://localhost:8000/api/v1/updates/<client_id>/<update_id>/quarantine
```

**Verification:** The update record status changes to `quarantined` and an audit event is enqueued.

**Escalation:** If multiple clients from the same IP range submit suspicious updates within one round, treat as a coordinated attack. Suspend aggregation for that round.

**Never:** Approve a suspicious update to "see what happens" — this introduces untrusted weights into the aggregation.

---

## Scenario 2 — Invalid Signature on Update Submission

**Detection signals:**
- `POST /api/v1/updates/submit` returns `422 Unprocessable Entity` with `detail` containing `signature`
- Server log shows `SignatureVerificationError`

**Operator action:**
1. The update is automatically rejected by the ingestion layer — no manual action is needed to block it.
2. Log the `client_id` and `update_id` from the request body.
3. Determine if the client's key was rotated without registering the new key.
4. If accidental key rotation: re-register the client key (Scenario 10).
5. If unexplained: quarantine all future submissions from this client until key provenance is confirmed.

**Commands:**
```powershell
# Check registered trusted keys
python -m scripts.list_trusted_keys
```

**Escalation:** More than 3 signature failures from one client in one round indicates key compromise or software fault.

**Never:** Register an unverified key to "fix" a signature failure without investigating the cause.

---

## Scenario 3 — Tampered Payload Detected

**Detection signals:**
- `POST /api/v1/updates/submit` returns `400 Bad Request` with `detail` containing `hash` or `checksum`
- Server log shows `PayloadIntegrityError`

**Operator action:**
1. The ingestion layer rejects tampered payloads automatically.
2. Record the `client_id` and the round number.
3. If systematic (multiple clients, same round): investigate whether the aggregation pipeline or coordinator has been compromised.
4. Contact the FL coordinator operator to compare payload hashes independently.

**Escalation:** Any evidence of in-transit modification requires a full network path audit.

**Never:** Manually reconstruct or re-accept a payload whose hash failed verification.

---

## Scenario 4 — Replay Attack Detected

**Detection signals:**
- `POST /api/v1/updates/submit` returns `409 Conflict` or `422` with `detail` containing `replay` or `update_id already exists`
- Repeated submissions of the same `update_id` from same or different clients

**Operator action:**
1. The replay protection layer rejects duplicates automatically.
2. If the client reports submitting legitimately and their submission is being rejected, confirm with the client that their `update_id` generation is non-deterministic.
3. If the replay comes from a different IP than the original client, investigate the FL coordinator network for MITM or replay injection.

**Commands:**
```powershell
# Confirm the existing record status
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/updates/pending `
  | python -m json.tool
```

**Escalation:** Coordinated replays across multiple clients indicate network-layer interception.

---

## Scenario 5 — Quarantined Update Requires Resolution

**Detection signals:**
- Dashboard shows quarantine queue depth > 0
- Quarantined update is from a known-good client

**Operator action:**
1. Review the quarantine reason and `anomaly_reasons` on the approval record.
2. If the detection was a false positive (e.g., legitimate high-magnitude update after a learning-rate change):
   - Re-approve the update with a detailed reason documenting the false positive.
   - Consider adjusting the detection threshold (see `configs/detection_dataset_inventory.md`).
3. If the detection is confirmed correct: reject the update.

**Commands:**
```powershell
# Approve a quarantined update (after investigation)
curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" `
  -d '{"reason": "Verified false positive: learning rate schedule change caused elevated L2 norm. See investigation note #123."}' `
  http://localhost:8000/api/v1/updates/<client_id>/<update_id>/approve
```

**Escalation:** If the same threshold triggers false positives repeatedly, re-calibrate thresholds using `scripts/evaluate_detector.py` before the next round.

---

## Scenario 6 — Rejected Update — Client Dispute

**Detection signals:**
- Client reports their update was rejected
- Dashboard shows the update in the rejected state with an operator-entered reason

**Operator action:**
1. Retrieve the rejection reason from the approval record.
2. Share the documented reason with the client (via secure channel — do not expose internal logs).
3. If the rejection was an error: there is no undo. The client must resubmit for the next round.
4. Document the correction in a new approval audit event if applicable.

**Never:** Delete or modify audit records to hide an erroneous rejection.

---

## Scenario 7 — Aggregation Gate Failure

**Detection signals:**
- `POST /api/v1/aggregation/run` returns `422` with `detail` listing updates that are not in `approved` status
- FL coordinator reports aggregation failed

**Operator action:**
1. Identify which `update_id`s are failing the gate check.
2. For each: confirm status is `approved` before retrying aggregation.
3. If updates are stuck in `pending_approval` or `quarantined`: resolve via dashboard before retrying.
4. If updates are `rejected`: those updates cannot be included. Notify the FL coordinator to exclude them.

**Commands:**
```powershell
# Check approval queue
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/updates/pending `
  | python -m json.tool
```

**Escalation:** If the aggregation gate fails repeatedly for a client whose submissions are legitimate, the approval pipeline may have a configuration error.

---

## Scenario 8 — Audit Event Delivery Failure

**Detection signals:**
- Dashboard Audit Outbox shows `pending_count` > 0 and persistent non-zero count over multiple refresh cycles
- Server log shows `DeliveryError` or `httpx.ConnectError` for the webhook URL

**Operator action:**
1. Confirm the webhook endpoint is reachable:
   ```powershell
   curl -I $env:FINSENTINEL_AUDIT_WEBHOOK_URL
   ```
2. If the endpoint is unreachable: resolve the network/SIEM issue. Events will be retried automatically on the next delivery cycle.
3. If the endpoint requires a new bearer token: update `FINSENTINEL_AUDIT_WEBHOOK_TOKEN` and restart the service.
4. Monitor `pending_count` after the restart; it should drain toward 0.

**Verification:** After fix, `pending_count` decreasing on each dashboard refresh.

**Escalation:** If `pending_count` stops decreasing after a confirmed SIEM fix, check for disk I/O issues or database deadlocks.

---

## Scenario 9 — Dead-Letter Queue Recovery

**Detection signals:**
- Dashboard shows `dead_letter_count` > 0
- Dashboard shows `outbox.alert = true` (red banner)

**Operator action:**
1. Investigate the failed records:
   ```powershell
   python -m scripts.list_dead_letter_events
   ```
2. Determine whether the failure was transient (network outage, SIEM downtime) or structural (bad payload, misconfigured URL).
3. For transient failures: after resolving the root cause, re-queue selectively:
   ```powershell
   python -m scripts.requeue_dead_letter --record-id <id>
   ```
4. For structural failures: do not re-queue until the root cause is fixed. Document the undelivered events and notify the SIEM operator.

**Escalation:** If dead-letter count exceeds 100, an audit gap exists. Escalate to the SIEM team immediately with the event list.

**Never:** Re-queue events without first fixing the root cause — this will only re-fail and waste retry budget.

---

## Scenario 10 — Operator Token Compromise / Rotation

**Detection signals:**
- Token leaked in logs, incident report, or access by unauthorized party
- Unexpected authenticated requests to `/api/v1/operator/*` from unfamiliar IPs

**Operator action:**
1. Generate a new 32+ character cryptographically random token:
   ```powershell
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```
2. Update `FINSENTINEL_OPERATOR_TOKEN` in the service environment.
3. Restart the service immediately:
   ```powershell
   nssm restart FinSentinel
   # or
   Get-Service FinSentinel | Restart-Service
   ```
4. Verify the old token is rejected: attempt a request with the old token and confirm `401`.
5. Update the token in the operator's password manager and any automation scripts.

**For client key rotation** (a client's Ed25519 private key is compromised):
```powershell
python -m scripts.revoke_trusted_key --key-id <key_id>
python -m scripts.register_trusted_key --public-key <new_key.pem> --client-id <client_id>
```

**Never:** Rotate a token by modifying the `.env` file without restarting the service — the old token remains active until restart.

---

## Scenario 11 — Database Outage

**Detection signals:**
- All API endpoints return `500 Internal Server Error`
- Server log shows `psycopg.OperationalError` or `sqlalchemy.exc.DBAPIError`
- Health check `GET /api/v1/health` returns `503` or fails to connect

**Operator action:**
1. Confirm PostgreSQL is running:
   ```powershell
   Get-Service postgresql*
   pg_isready -h localhost -p 5432
   ```
2. Restart PostgreSQL if stopped:
   ```powershell
   Start-Service postgresql-x64-18
   ```
3. After PostgreSQL recovers, restart FinSentinel to re-establish connection pool:
   ```powershell
   nssm restart FinSentinel
   ```
4. Verify: `GET /api/v1/health` returns `{"status": "ok"}`.

**During outage:** Incoming client submissions are rejected with `503`. The FL coordinator must pause submission or buffer updates. No approval processing is possible during the outage.

**Escalation:** Data loss risk if PostgreSQL crashes without WAL archiving. Verify backup status before declaring the outage resolved.

---

## Scenario 12 — Delivery Worker Failure

**Detection signals:**
- Dashboard shows worker status `disabled` or `Worker: disabled` badge in Audit Outbox
- `pending_count` growing but not draining despite a configured webhook URL
- Server log shows `WorkerError` or thread exception

**Operator action:**
1. Check the worker status:
   ```powershell
   curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/health/metrics `
     | python -m json.tool
   ```
2. Restart FinSentinel to restart the delivery worker thread:
   ```powershell
   nssm restart FinSentinel
   ```
3. Confirm `FINSENTINEL_AUDIT_DELIVERY_WORKER_ENABLED=true` is set in the service environment.
4. After restart, monitor `pending_count` for 60 seconds to confirm events drain.

**Escalation:** If the worker crashes repeatedly after restart, check server logs for `WorkerError` and investigate the webhook endpoint stability.

---

## Scenario 13 — Safe Shutdown for Maintenance

**Purpose:** Graceful shutdown that does not corrupt in-flight requests or leave transactions open.

**Operator action:**
1. Drain in-flight requests by sending `SIGTERM` via service stop (uvicorn handles graceful shutdown):
   ```powershell
   nssm stop FinSentinel
   # Waits for in-flight requests to complete (uvicorn graceful timeout)
   ```
2. Verify shutdown:
   ```powershell
   nssm status FinSentinel
   # Expected: SERVICE_STOPPED
   ```
3. Perform maintenance (database backup, migration, config update).
4. After maintenance:
   ```powershell
   nssm start FinSentinel
   nssm status FinSentinel
   # Expected: SERVICE_RUNNING
   curl -s http://localhost:8000/api/v1/health
   ```

**For Alembic migrations during maintenance window:**
```powershell
.\venv-security\Scripts\activate
alembic upgrade head
alembic current   # confirm head matches expected revision
```

**Never:** Kill the process with `taskkill /F` during active request processing — use `nssm stop` or `Stop-Service` which sends the graceful shutdown signal.

---

## Quick Reference — API Commands

| Action | Method | Path | Auth |
|---|---|---|---|
| Check health | `GET` | `/api/v1/health` | None |
| Get dashboard | `GET` | `/api/v1/operator/dashboard` | Bearer |
| Get pending approvals | `GET` | `/api/v1/updates/pending` | Bearer |
| Approve update | `POST` | `/api/v1/updates/{client}/{id}/approve` | Bearer |
| Reject update | `POST` | `/api/v1/updates/{client}/{id}/reject` | Bearer |
| Quarantine update | `POST` | `/api/v1/updates/{client}/{id}/quarantine` | Bearer |
| Get health metrics | `GET` | `/api/v1/health/metrics` | Bearer |
| Get health alerts | `GET` | `/api/v1/health/alerts` | None |

---

*Created: 2026-11-19 (Entry 59)*
