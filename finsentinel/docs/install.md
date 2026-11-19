# FinSentinel Installation Guide

## Requirements

- Windows 10/11 (64-bit) or Windows Server 2019+
- Python 3.13
- PostgreSQL 15+ (for production; SQLite used for tests only)
- nginx (optional, for TLS termination — see `configs/nginx.conf`)
- NSSM (optional, for Windows service — see `configs/windows_startup.md`)

---

## 1. Clone and Create Virtual Environment

```bash
git clone <repo-url> finsentinel
cd finsentinel
python -m venv venv-security
.\venv-security\Scripts\activate
pip install -e ".[dev]"
```

---

## 2. Database Setup

Create a PostgreSQL database and user:

```sql
CREATE DATABASE finsentinel;
CREATE USER finsentinel_user WITH PASSWORD 'choose-a-strong-password';
GRANT ALL PRIVILEGES ON DATABASE finsentinel TO finsentinel_user;
```

Run migrations:

```bash
alembic upgrade head
```

---

## 3. Environment Variables

Copy `.env.example` to `.env` and fill in all values.

### Required

| Variable | Description |
|---|---|
| `DB_USER` | PostgreSQL user |
| `DB_PASSWORD` | PostgreSQL password |
| `DB_HOST` | PostgreSQL host |
| `DB_NAME` | PostgreSQL database name |
| `FINSENTINEL_OPERATOR_TOKEN` | Bearer token for operator-authenticated endpoints |
| `FINSENTINEL_ALLOWED_MODEL_VERSIONS` | Comma-separated list of allowed model version strings |
| `FINSENTINEL_ALLOWED_ROUNDS` | Comma-separated list of allowed training round numbers |

### Recommended for Production

| Variable | Description |
|---|---|
| `FINSENTINEL_MAX_UPDATE_AGE_SECONDS` | Maximum envelope age in seconds (default: 900) |
| `FINSENTINEL_MAX_CONCURRENT_INGESTION` | Per-process ingestion concurrency cap |
| `FINSENTINEL_INGESTION_RATE_LIMIT_RPM` | Per-IP rate limit (requests/minute) |
| `FINSENTINEL_BODY_READ_TIMEOUT_SECONDS` | Body-read deadline (seconds) |
| `FINSENTINEL_AUDIT_DELIVERY_WORKER_ENABLED` | Set to `1` to enable background delivery |
| `FINSENTINEL_AUDIT_WEBHOOK_URL` | SIEM webhook endpoint URL (HTTPS required for non-loopback) |
| `FINSENTINEL_AUDIT_WEBHOOK_TOKEN` | Bearer token for webhook authentication |

### Optional

| Variable | Description |
|---|---|
| `FINSENTINEL_SAMPLE_COUNT_TRUST_MODE` | `client_claimed` (default) or `coordinator_verified` |
| `FINSENTINEL_COORDINATOR_URL` | Coordinator HTTP endpoint (required for `coordinator_verified` mode) |
| `FINSENTINEL_COORDINATOR_TOKEN` | Bearer token for coordinator requests |
| `ENVIRONMENT` | Set to `test` to enable fallback detection thresholds |

---

## 4. Start the Server

### Development

```bash
.\venv-security\Scripts\uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Production (via NSSM Windows Service)

See `configs/windows_startup.md` for complete NSSM configuration instructions.

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4 \
    --proxy-headers --forwarded-allow-ips "*"
```

### Production (behind nginx)

See `configs/nginx.conf`. nginx handles TLS termination and rate limiting.
uvicorn listens on `127.0.0.1:8000` only.

---

## 5. Register Trusted Keys and Model Schemas

Before accepting client updates, register each client's public key:

```python
from core.key_registry import register_trusted_key
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

register_trusted_key(
    key_id="client-001-key",
    client_id="client-001",
    public_key=<Ed25519PublicKey>,
    max_sample_count=50_000,
)
```

Register the model schema (once per model version):

```python
from core.model_registry import register_model_schema
import torch

register_model_schema(
    model_version="v1",
    state_dict={
        "layer.weight": torch.zeros((256, 128), dtype=torch.float32),
        "layer.bias": torch.zeros(256, dtype=torch.float32),
    },
)
```

---

## 6. Run Tests

```bash
.\venv-security\Scripts\python -m pytest --tb=short -q
```

Expected output: 632 passed, 3 skipped (PostgreSQL concurrent tests), 1 warning.

---

## 7. Health Check

```bash
curl http://localhost:8000/api/v1/health
```

```bash
curl -H "Authorization: Bearer $FINSENTINEL_OPERATOR_TOKEN" \
     http://localhost:8000/api/v1/operator/dashboard
```
