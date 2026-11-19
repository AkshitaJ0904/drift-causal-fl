# FinSentinel — Windows Production Startup Guide

## Prerequisites

- Python 3.13 installed (python.exe on PATH or use full path)
- PostgreSQL 18.x running (native or via service)
- `venv-security` created and dependencies installed via `pip install -e ".[dev]"`
- All environment variables from `.env.example` populated in a `.env` file or
  as system/process environment variables. Never commit `.env` to version control.

## Environment variables (minimum required for production)

```
FINSENTINEL_OPERATOR_TOKEN=<32+ char random token>
DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/finsentinel?sslmode=require
FINSENTINEL_AUDIT_DELIVERY_WORKER_ENABLED=true
FINSENTINEL_AUDIT_WEBHOOK_URL=https://your-siem.example.com/events
FINSENTINEL_AUDIT_WEBHOOK_TOKEN=<bearer token for SIEM>
FINSENTINEL_MAX_CONCURRENT_INGESTION=20
FINSENTINEL_INGESTION_RATE_LIMIT_RPM=300
FINSENTINEL_BODY_READ_TIMEOUT_SECONDS=30
```

## Running with uvicorn (foreground, for testing)

```powershell
# From the finsentinel directory, with venv-security activated:
.\venv-security\Scripts\activate
$env:DATABASE_URL = "postgresql+psycopg://..."
$env:FINSENTINEL_OPERATOR_TOKEN = "..."
# ... set all required vars ...
python -m uvicorn app.main:app `
    --host 0.0.0.0 `
    --port 8000 `
    --workers 2 `
    --proxy-headers `
    --forwarded-allow-ips="127.0.0.1"
```

**Required production flags:**
- `--proxy-headers`: enables `X-Forwarded-For` / `X-Forwarded-Proto` parsing.
  Required when running behind nginx.
- `--forwarded-allow-ips="127.0.0.1"`: trust XFF only from nginx. Prevents
  clients from spoofing their source IP.
- `--workers N`: set to CPU count or 2× for I/O-heavy loads. Each worker starts
  its own outbox delivery thread.

## Windows Service via NSSM (Non-Sucking Service Manager)

NSSM wraps any executable as a Windows service with automatic restart.

### Installation

1. Download NSSM from https://nssm.cc/download
2. Extract `nssm.exe` to `C:\tools\nssm\` and add to PATH.

### Create service

```powershell
# Run as Administrator:
nssm install FinSentinel "D:\prj 4\drift-causal-fl\finsentinel\venv-security\Scripts\python.exe"
nssm set FinSentinel AppParameters "-m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2 --proxy-headers --forwarded-allow-ips=127.0.0.1"
nssm set FinSentinel AppDirectory "D:\prj 4\drift-causal-fl\finsentinel"
nssm set FinSentinel AppEnvironmentExtra `
    "DATABASE_URL=postgresql+psycopg://..." `
    "FINSENTINEL_OPERATOR_TOKEN=..." `
    "FINSENTINEL_AUDIT_DELIVERY_WORKER_ENABLED=true" `
    "FINSENTINEL_AUDIT_WEBHOOK_URL=https://siem.example.com/events" `
    "FINSENTINEL_AUDIT_WEBHOOK_TOKEN=..."
nssm set FinSentinel AppStdout "D:\prj 4\drift-causal-fl\finsentinel\logs\stdout.log"
nssm set FinSentinel AppStderr "D:\prj 4\drift-causal-fl\finsentinel\logs\stderr.log"
nssm set FinSentinel AppRotateFiles 1
nssm set FinSentinel AppRotateBytes 10485760   # 10 MB
nssm set FinSentinel Start SERVICE_AUTO_START
nssm start FinSentinel
```

### Verify

```powershell
nssm status FinSentinel
# Expected: SERVICE_RUNNING
Get-Service FinSentinel
```

### Stop / remove

```powershell
nssm stop FinSentinel
nssm remove FinSentinel confirm
```

## Alternative: Task Scheduler (no NSSM)

If NSSM is not available, use Windows Task Scheduler:
- Trigger: At system startup
- Action: `python.exe -m uvicorn app.main:app ...` (full path to python in venv)
- Working directory: `D:\prj 4\drift-causal-fl\finsentinel`
- Run as: a dedicated service account (not an interactive user account)

## Security checklist before first start

Each item is marked with its enforcement source so an operator can verify
independently. Code references are relative to `finsentinel/`.

- [ ] **`FINSENTINEL_OPERATOR_TOKEN` set to a cryptographically random 32+ char string**
  - *Code-enforced:* `app/main.py` logs a WARNING at startup when the token is absent
    (all operator endpoints return HTTP 503). `api/_auth.py::check_operator_token_strength()`
    logs an ERROR when the token is present but fewer than 32 characters — startup
    continues but the token is guessable. The auth function (`api/_auth.py::require_operator_auth`)
    rejects any presented token that does not match via `hmac.compare_digest`.
  - *Limitation:* A short token does NOT block startup; it only logs an error. Enforce
    minimum length in the deployment procedure before service start.
  - *Verify:* `GET /api/v1/health` returns 200 regardless; `GET /api/v1/operator/dashboard`
    returns 401 without a valid token.

- [ ] **Database connection always uses SSL**
  - *Code-enforced:* `core/config.py::Settings.database_url` constructs the SQLAlchemy URL
    with `sslmode=require` hardcoded in the query parameters — it is never omitted regardless
    of environment variables. There is no `DATABASE_URL` env var; the URL is assembled from
    `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`, and `DB_NAME`.
  - *Verify:* Inspect `core/config.py::database_url` property; `sslmode` is always `require`
    in the constructed URL object.

- [ ] **`FINSENTINEL_AUDIT_WEBHOOK_URL` is HTTPS (not HTTP, unless localhost)**
  - *Code-enforced:* `audit/delivery.py::_validate_webhook_url` raises `DeliveryConfigError`
    for plain HTTP to any non-loopback host. `app/main.py` calls `create_webhook_delivery_fn()`
    at startup and wraps the error as `RuntimeError`, blocking startup when the URL is invalid.
    HTTP is only accepted for `localhost`, `127.0.0.1`, and `[::1]` (dev/test use only).
  - *Verify:* Set URL to `http://external-host/endpoint` and confirm startup failure.

- [ ] **Log directory exists and is writable by the service account**
  - *Deployment responsibility.* No code validation. NSSM's `AppStdout` / `AppStderr`
    paths will cause the service to fail silently if the directory is missing or unwritable.
  - *Verify:* `New-Item -ItemType Directory -Force D:\prj 4\drift-causal-fl\finsentinel\logs`;
    confirm the service account has `(W)` access via `icacls logs`.

- [ ] **`.env` file (if used) is NOT readable by other Windows users**
  - *Deployment responsibility.* No code validation.
  - *Verify:* `icacls .env` — only the service account and Administrators should appear.
    Remove broad access: `icacls .env /inheritance:r /grant:r "SERVICEACCOUNT:(R)"`.

- [ ] **Alembic migrations applied: `alembic upgrade head`**
  - *Deployment responsibility.* No application-startup enforcement. `alembic check` is
    only run in the CI `migration-smoke` job (`.github/workflows/ci.yml`), not at runtime.
    A running server does not detect a schema mismatch automatically — a stale schema will
    cause SQLAlchemy errors on affected endpoints rather than a clean startup failure.
  - *Operator action before start:* Run `alembic upgrade head` and confirm with
    `alembic current` (should report same revision as `alembic heads`).
  - *Verify:* `alembic current` should report the same revision as `alembic heads`.

- [ ] **Firewall: port 8000 blocked externally; nginx on 443 is the public entry point**
  - *Deployment responsibility.* No code validation.
  - *Verify:* From an external host, confirm port 8000 is unreachable and port 443
    (nginx → uvicorn proxy) returns a valid TLS response.
  - *Note:* nginx configuration is covered in `configs/nginx_site.conf` (deployment-dependent;
    see Sprint 3 deployment-dependent requirements in `docs/requirement_matrix.md`).
