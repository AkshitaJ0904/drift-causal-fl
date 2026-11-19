# FinSentinel Architecture

## Overview

FinSentinel is a Windows-native security layer for federated-learning (FL) model
updates. It sits between FL clients and the aggregation server, enforcing
cryptographic authentication, anomaly detection, approval workflows, and
tamper-evident audit logging with reliable external delivery.

---

## Component Map

```
FL Client
    │
    │  HTTPS  POST /api/v1/updates
    ▼
┌─────────────────────────────────────────────────────────────┐
│  FastAPI application  (app/main.py)                         │
│                                                             │
│  Middleware stack (outermost → innermost):                  │
│    IngestionRateLimitMiddleware  — per-IP token bucket       │
│    IngestionConcurrencyMiddleware — slot gate               │
│    RequestBodyLimitMiddleware    — size limit + read timeout │
│                                                             │
│  /api/v1/updates  (api/ingestion.py)                        │
│    1. Verify Ed25519 signature   (core/crypto.py)           │
│    2. Replay-protection check    (core/replay_protection.py)│
│    3. Policy check               (policy/model_update_policy│
│    4. Schema validation          (core/model_registry.py)   │
│    5. Payload integrity (SHA-256)(ingestion/payload.py)     │
│    6. Anomaly detection          (detection/rule_based.py)  │
│    7. Register for approval      (enforcement/approval_srv) │
│    8. Enqueue audit event        (audit/outbox.py)          │
│                                                             │
│  /api/v1/approvals (api/approval.py)                        │
│    Operator approves/rejects updates                        │
│                                                             │
│  /api/v1/aggregate (api/aggregation.py)                     │
│    FedAvg aggregation of approved updates                   │
│                                                             │
│  /api/v1/operator/dashboard (api/dashboard.py)              │
│    Authenticated operational summary                        │
│                                                             │
│  Background: OutboxDeliveryWorker (audit/worker.py)         │
│    Calls deliver_pending_events() in a loop                 │
│    HTTP webhook delivery (audit/delivery.py)                │
└──────────────────────────┬──────────────────────────────────┘
                           │
                    ┌──────┴──────┐
                    │  Database   │
                    │  (SQLAlchemy│
                    │  + Postgres)│
                    │  Tables:    │
                    │  audit_events       │
                    │  audit_outbox       │
                    │  trusted_keys       │
                    │  model_schemas      │
                    │  replay_records     │
                    │  update_approvals   │
                    └─────────────┘
                           │
                    ┌──────┴──────┐
                    │  SIEM/Webhook│
                    │  (external) │
                    └─────────────┘
```

---

## Security Layers

### 1. Transport (nginx)
- TLS 1.2/1.3 termination
- HSTS, rate limiting (`limit_req_zone`), body size cap
- `X-Forwarded-For` injection for real-IP tracking

### 2. Authentication (Ed25519)
- Every update is signed by the FL client's Ed25519 private key
- Server holds a registry of trusted public keys (`core/key_registry.py`)
- Signing covers envelope metadata (not payload) via `canonical_signed_data()`

### 3. Replay Protection
- Each `(client_id, update_id)` pair is reserved atomically before processing
- Duplicate submissions return HTTP 409

### 4. Policy Enforcement
- `FINSENTINEL_ALLOWED_MODEL_VERSIONS` and `FINSENTINEL_ALLOWED_ROUNDS` gate
  which updates are accepted
- Timestamp freshness window (`FINSENTINEL_MAX_UPDATE_AGE_SECONDS`)

### 5. Anomaly Detection
- Rule-based feature extraction (L2 norm, std, mean, zero-fraction)
- Configurable thresholds via `RuleBasedDetectionConfig`
- Suspicious updates flagged and routed through approval workflow

### 6. Approval Workflow
- All updates (clean and suspicious) register in the approval queue
- Operator approves via `POST /api/v1/approvals/{update_id}/approve`
- Aggregation only processes approved updates

### 7. Audit Outbox (Transactional)
- Every security event is enqueued to `audit_outbox` in the same DB transaction
  as the ingestion operation (at-least-once, durable)
- Three-phase delivery: claim → deliver (outside transaction) → ack
- Dead-lettering after `MAX_DELIVERY_ATTEMPTS` (default 5)
- Idempotency key stable across retries

### 8. HTTP Webhook Delivery
- SSRF-safe URL validation (blocks RFC 1918, loopback, link-local, etc.)
- Bearer-token auth header
- 4xx responses → immediate dead-letter (permanent failure)
- 5xx / network errors → exponential backoff with jitter

---

## Key Design Decisions

| Decision | Rationale |
|---|---|
| Three-phase outbox delivery | No DB transaction held open during network I/O |
| StaticPool for tests | In-memory SQLite shared across all test sessions |
| httpx (canonical) | httpx2 was an orphaned fork; canonical httpx 0.28.1 used |
| Per-record mini-transactions in Phase 3 | Partial batch failures don't roll back successful acks |
| `claimed_until` column | Claim TTL expiry for record reclaimability after crash |
| `SELECT FOR UPDATE SKIP LOCKED` | Concurrent worker processes don't double-claim records |

---

## Coordinator Integration (Sprint 4)

`HttpCoordinatorAdapter` (`coordination/http_coordinator.py`) implements the
`CoordinatorAdapter` protocol. It queries an external FL coordinator for:
- Expected sample counts per client per round
- Whether a client is selected for a round

Thread-safe (single `threading.Lock`), bounded timeout, SSRF-guarded URL
validation, returns `None` on any connectivity or parse error (graceful
degradation).
