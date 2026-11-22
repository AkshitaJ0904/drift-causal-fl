# FinSentinel — Wazuh SIEM Integration

Phase 2 of the FinSentinel security gateway adds a Wazuh 4.8 SIEM layer that
receives, decodes, and alerts on every security event emitted by the
Federated Learning ingestion pipeline.

---

## Architecture

```
Windows host
  FastAPI backend (:8000)   frontend (:5173)   siem_forwarder (:9999)
       │                                              ▲
       │  audit outbox → delivery worker              │ Bearer POST
       │                        │                     │
       │                        └────────────────────►│
       │                                              │
       └─► logs/finsentinel-siem.jsonl  ◄─────────────┘
                                      (DrvFs mount)

WSL2 Ubuntu (Docker Compose)
  wazuh-manager  ──── localfile monitor (json) ────► analysisd
       │                   reads /finsentinel-logs/*.jsonl
       │                        │
       │              custom decoder (finsentinel.xml)
       │              + rules 100100–100140 (if_sid: 86600 chain)
       │                        │
       └────────────────────────► wazuh-indexer (OpenSearch :9200)
                                       │
                               wazuh-dashboard (:443)
  postgres (:5432) ─ finsentinel_migration_test DB (concurrent outbox tests)
```

Event flow: `audit_outbox → delivery worker → POST :9999 → JSONL → analysisd → alert`

---

## Prerequisites

| Requirement | Notes |
|---|---|
| Windows 11 with WSL2 | `wsl --install` if not already enabled |
| Ubuntu 22.04 LTS in WSL2 | Default distribution |
| Docker Engine (in WSL2) | Installed by `setup-wsl.sh` |
| Python 3.13 + `venv-security` | On the Windows host |
| FinSentinel backend running | `python scripts/run_dev.py` |

---

## Quick Start

### 1. Enable WSL2 (one-time, requires reboot)

```powershell
wsl --install
# Reboot, then set your Ubuntu username and password
```

### 2. Configure passwords

```bash
# Inside WSL2 Ubuntu
cd /mnt/d/prj\ 4/drift-causal-fl/finsentinel/deploy/wazuh
cp .env.example .env
nano .env   # set WAZUH_INDEXER_PASSWORD, WAZUH_API_PASSWORD,
            # POSTGRES_PASSWORD, FINSENTINEL_LOGS_DIR
```

**Never commit `.env`.** It is gitignored by `.env.example` convention.

### 3. Run the bootstrap script

```bash
chmod +x setup-wsl.sh
./setup-wsl.sh
```

This script:
- Installs Docker Engine via the official apt repo
- Sets `vm.max_map_count=262144` (required by Wazuh Indexer / OpenSearch)
- Creates the SIEM log directory
- Starts all services with `docker compose up -d`

### 4. Wait for services to be healthy

```bash
docker compose ps          # all should show "healthy" or "running"
docker compose logs -f wazuh-manager   # watch for "INFO: Wazuh started"
```

The Wazuh dashboard typically takes 2–3 minutes on first start.

---

## Services

| Service | Port | Purpose |
|---|---|---|
| Wazuh Dashboard | https://localhost | SIEM alert viewer (Threat Hunting, Security Events) |
| Wazuh REST API | https://localhost:55000 | Rule reload, logtest, cluster health |
| FinSentinel UI | http://localhost:5173 | **Operator decisions**: approve / reject / quarantine |
| FinSentinel API | http://localhost:8000 | Backend (ingestion, audit, operator API) |
| PostgreSQL | localhost:5432 | FinSentinel concurrent-outbox test database |

Credentials: local-dev default, see `~/finsentinel-wazuh/.env`.

Access the Wazuh dashboard at `https://<WSL2-IP>` from Windows (find the IP with
`ip addr show eth0` inside WSL2).

> **Important:** Operator approve/reject/quarantine decisions are made in the
> **FinSentinel UI at http://localhost:5173** (Approvals page). The Wazuh dashboard
> is for SIEM alert viewing only — not for operator actions.

---

## Custom Decoder and Rules

### Decoder — `decoders/finsentinel.xml`

Matches any line beginning with `{"timestamp":` and routes it through
Wazuh's built-in JSON decoder, which extracts all fields as `data.<key>`.

### Rules — `rules/finsentinel_rules.xml`

| Rule ID | Level | Event Type | MITRE |
|---|---|---|---|
| 100100 | 0 | (anchor — if_sid: 86600) | — |
| 100101 | 3 | security.update_authenticated | — |
| 100102 | 3 | security.update_pending_approval | — |
| 100103 | 10 | security.update_quarantined | T1565.001 |
| 100104 | 12 | security.signature_verification_failed | T1553 |
| 100105 | 12 | security.replay_detected | T1550 |
| 100106 | 10 | security.anomaly_detected | T1565.001 |
| 100107 | 10 | security.model_schema_rejected | T1565.002 |
| 100108 | 10 | security.policy_rejected.* | T1078 |
| 100109 | 10 | security.sample_count_limit_exceeded | T1565.002 |
| 100110 | 12 | security.sample_count_limit_missing | — |
| 100111 | 7 | security.approval_registration_failed | — |
| 100112 | 10 | security.payload_integrity_failed | T1565.002 |
| 100113 | 12 | security.unknown_signing_key | T1553 |
| 100114 | 12 | security.client_key_mismatch | T1553 |
| 100115 | 10 | security.sample_count_mismatch | — |
| 100116 | 10 | security.sample_count_verification_required | — |
| 100117 | 7 | security.serialization_failed | — |
| 100118 | 3 | security.anomaly_clean | — |
| 100119 | 7 | security.audit_status_persistence_failed | — |
| 100120 | 3 | operator.update_approved | — |
| 100121 | 7 | operator.update_rejected | — |
| 100122 | 10 | operator.update_quarantined | T1565.001 |
| 100123 | 3 | operator.approve_requested | — |
| 100124 | 7 | operator.reject_requested | — |
| 100125 | 10 | operator.quarantine_requested | — |
| 100130 | 3 | schema.registered | — |
| 100131 | 3 | key.registered | — |
| 100132 | 7 | key.revoked | — |
| 100140 | 13 | brute force correlation (5 events/60s) | T1110 |
| 100119 | 7 | security.audit_status_persistence_failed — rule ready; event **not** emitted by the current backend (tracked internally, not forwarded to SIEM) | — |

Level 10+ events appear in the Wazuh dashboard security alerts view.
Level 12+ events trigger email/notification integrations if configured.
Level 13 (rule 100140) is a composite brute-force alert fired by `<if_matched_sid>100104</if_matched_sid>`:
it counts only `security.signature_verification_failed` events (rule 100104).
Events from unknown-key (100113) or key-mismatch (100114) do **not** increment the 100140 counter.

### Severity Legend

The "FinSentinel Security Overview" dashboard uses a scripted field to map
Wazuh alert levels to human-readable severity labels:

| Level range | Severity | Meaning |
|---|---|---|
| ≤ 4 | **Low** | Informational (authenticated updates, key registrations) |
| 5 – 9 | **Medium** | Soft policy / operator actions (rejections, quarantines) |
| 10 – 12 | **High** | Active attack or integrity violation blocked (single event) |
| ≥ 13 | **Critical** | Correlated multi-event attack (brute force: rule 100140) |

---

## Dashboards

### FinSentinel Security Overview

A pre-built OpenSearch Dashboards dashboard with four panels:

| Panel | Type | Shows |
|---|---|---|
| Alerts by Severity | Donut pie | Distribution across Low / Medium / High / Critical |
| Alerts Over Time | Date histogram | Alert volume per time bucket |
| Top Attack Types | Horizontal bar | Rule descriptions ranked by count (level ≥ 7 only) |
| Recent Alerts Table | Table | Time · Severity · Description · Client |

**Import (idempotent):**

```bash
# WSL2 — from deploy/wazuh/
source ~/finsentinel-wazuh/.env
bash import_dashboard.sh
```

The import is safe to re-run. Existing objects are overwritten with no data loss.

**View:** `https://localhost/app/dashboards` → open "FinSentinel Security Overview".

The "severity" scripted field (Painless) is embedded in `dashboards/finsentinel.ndjson`
and is automatically available in every visualization on the dashboard. See the
[Severity Legend](#severity-legend) in the Rules section above.

---

## Windows Agent (optional)

Install the Wazuh 4.8 Windows agent MSI from the Wazuh downloads page, then
add the localfile fragment from `agent/ossec-localfile.conf` to
`C:\Program Files (x86)\ossec-agent\ossec.conf`:

```xml
<localfile>
  <log_format>json</log_format>
  <location>C:\Users\Hp\.finsentinel\siem\finsentinel-siem.jsonl</location>
</localfile>
```

Restart the agent service after editing.

Without the agent, map `FINSENTINEL_LOGS_DIR` in `.env` to the Windows path
via WSL2 (`/mnt/c/Users/Hp/.finsentinel/siem`) so the manager container can
read the file directly.

---

## E2E Proof Script

```powershell
# 1. Start the FinSentinel backend
.\venv-security\Scripts\python.exe scripts\run_dev.py

# 2. In a second terminal, run the proof script
.\venv-security\Scripts\python.exe scripts\demo_wazuh_events.py
```

With `WAZUH_API_PASSWORD` unset it writes events to the JSONL file and exits
cleanly (`PASS — events written to JSONL; Wazuh query skipped`).

To also verify alerts in Wazuh:

```powershell
$env:WAZUH_API_PASSWORD = "your-password-here"
.\venv-security\Scripts\python.exe scripts\demo_wazuh_events.py
```

---

## PostgreSQL-enabled Tests

> **Important:** These tests MUST run from WSL Linux — not Windows.
> Windows WDAC blocks the psycopg binary DLL. Use a dedicated Linux venv.

```bash
# WSL2 — one-time venv setup
cd /mnt/d/prj\ 4/drift-causal-fl/finsentinel
python3 -m venv ~/venv-finsentinel-pg --without-pip
# bootstrap pip from Windows venv
PYTHONPATH=/mnt/d/prj\ 4/drift-causal-fl/finsentinel/venv-security/Lib/site-packages \
  python3 -m pip install pip --target ~/venv-finsentinel-pg/lib/python3.*/site-packages/
~/venv-finsentinel-pg/bin/python3 -m pip install \
  "psycopg[binary]>=3.2,<4.0" "SQLAlchemy>=2.0,<3.0" "alembic>=1.15,<2.0" \
  "pytest>=8.3" "pydantic>=2.0" "pydantic-settings>=2.7,<3.0" \
  "cryptography>=44" "python-dotenv>=1.0" "httpx>=0.27,<1.0" \
  "numpy>=2.0,<3.0" "scikit-learn>=1.6,<2.0" "xgboost>=2.1,<4.0"
~/venv-finsentinel-pg/bin/python3 -m pip install --no-deps -e .

# Run alembic migrations (uses DB_* env vars — not DATABASE_URL)
PG_PASS="$(grep '^POSTGRES_PASSWORD=' ~/finsentinel-wazuh/.env | cut -d= -f2-)"
DB_USER=finsentinel_migration_test \
DB_PASSWORD="$PG_PASS" \
DB_HOST=localhost \
DB_PORT=5432 \
DB_NAME=finsentinel_migration_test \
  ~/venv-finsentinel-pg/bin/python3 -m alembic upgrade head

# Run the 3 concurrent outbox tests
FINSENTINEL_POSTGRES_TEST=1 \
PG_MIGRATION_TEST_PASSWORD="$PG_PASS" \
  ~/venv-finsentinel-pg/bin/python3 -m pytest tests/test_postgres_outbox_concurrent.py -v
```

**Verified result:** 3 passed, 0 failed (2026-11-21).

---

## Useful Commands

```bash
# WSL2 — service management
docker compose up -d
docker compose down
docker compose logs -f wazuh-manager
docker compose ps

# WSL2 — test decoder against a sample event
echo '{"timestamp":"2026-11-19T12:00:00Z","event_type":"security.replay_detected","severity":"high","client_id":"c1","update_id":"u1","description":"Replay"}' \
  | docker exec -i wazuh-manager /var/ossec/bin/wazuh-logtest

# PowerShell (Windows) — view SIEM log
Get-Content logs\finsentinel-siem.jsonl -Tail 20
```

---

## Troubleshooting

### No finsentinel alerts in Wazuh (rule 86600 priority issue)

FinSentinel events contain `{"timestamp":…, "event_type":…}` fields. Wazuh's
built-in Suricata decoder (rule 86600) fires first on any JSON event with a
`timestamp` field. Rule 100100 therefore uses `<if_sid>86600</if_sid>` to
chain from rule 86600 — not `<decoded_as>json</decoded_as>`.

If you create new rules in this family, always chain from rule 100100 (not from
86600 directly) using `<if_sid>100100</if_sid>` and a matching `<field name="source">`.

After editing `finsentinel_rules.xml`, restart analysisd:
```bash
# From WSL2
TOKEN=$(curl -sk -u wazuh-wui:"$WAZUH_API_PASSWORD" \
  'https://localhost:55000/security/user/authenticate?raw=true')
curl -sk -X PUT "https://localhost:55000/manager/restart" \
  -H "Authorization: Bearer $TOKEN"
```

### DrvFs / JSONL not visible in container

The JSONL file is written from Windows (`logs/finsentinel-siem.jsonl`). Docker
mounts it at `/finsentinel-logs/finsentinel-siem.jsonl` (read-only). The DrvFs
path in WSL2 is `/mnt/d/prj 4/…` — set `FINSENTINEL_LOGS_DIR` in `.env` to
match your Windows drive letter.

### OOM / Wazuh Indexer killed

OpenSearch needs ≥ 4 GB RAM. Set `ES_JAVA_OPTS=-Xms1g -Xmx1g` in
`docker-compose.yml` or in WSL2 `~/.wslconfig` increase memory above 4 GB.

### analysisd stale process / SIGHUP

`kill -HUP <analysisd-pid>` fails inside the container because the binary name
resolution differs. Use the REST API restart shown above instead.

### WSL2 shuts down when no terminal is open (containers disappear)

**Cause:** WSL2 has a default idle timeout (8 seconds in some builds, variable in
others) that terminates the VM when no Windows process is attached. Docker and all
containers stop with it.

**Fix:** Create `%USERPROFILE%\.wslconfig` with `vmIdleTimeout=-1`:
```ini
[wsl2]
vmIdleTimeout=-1
```
Then apply with:
```powershell
wsl --shutdown          # apply the new setting
# open any WSL terminal — WSL restarts automatically
```
With `restart: unless-stopped` in `docker-compose.yml`, all 4 containers
auto-restart when Docker restarts. No `compose up -d` needed.

**Why `docker ps` shows "Up 1 second" after every WSL command:** WSL2 uptime
resets each time the VM starts. `docker inspect` shows `RestartCount=0` and
`State.Status=running` — the containers are healthy, only the displayed uptime is
misleading. This is a WSL2 artifact, not a container restart.

### Dashboard login fails (401 / blank page after restart)

**Cause:** `INDEXER_PASSWORD` in `~/finsentinel-wazuh/.env` does not match the
password OpenSearch was initialized with. This happens when `.env` is edited after
the first `compose up -d` (the OpenSearch volume remembers the original password;
only `OPENSEARCH_INITIAL_ADMIN_PASSWORD` on an empty volume takes effect).

**Fix:** Restore the local-dev default in `.env`:
```bash
# In WSL2 — edit INDEXER_PASSWORD back to the value in deploy/wazuh/.env.example
nano ~/finsentinel-wazuh/.env   # set INDEXER_PASSWORD=<default from .env.example>
# Then restart (NO -v — that would delete all alert data):
cd /mnt/d/prj\ 4/drift-causal-fl/finsentinel/deploy/wazuh
docker compose --env-file ~/finsentinel-wazuh/.env down
docker compose --env-file ~/finsentinel-wazuh/.env up -d
```

**Why Filebeat is unaffected:** Filebeat authenticates to OpenSearch with TLS client
certificates (`wazuh.manager.pem` / `wazuh.manager-key.pem`), not username/password.
Only the dashboard uses the `INDEXER_PASSWORD` credential.

**Note:** File permissions (0600, UID 1000) are NOT the cause — the container user
(UID 1000) matches the host user, so `0600` files are readable inside the container.

### Dead letters in audit Overview panel

**What they are:** Audit events that exhausted all 10 delivery retries are moved to
`dead_letter` status in `audit_outbox`. They are never silently deleted.

**Root cause:** The SIEM forwarder (`:9999`) was not running when the backend tried
to deliver. With the original `start-demo.py`, the wrong env var name
(`FINSENTINEL_DELIVERY_WORKER_ENABLED` vs `FINSENTINEL_AUDIT_DELIVERY_WORKER_ENABLED`)
was used, and `start_forwarder.py` was not called (skipping token loading).

**Fix applied:** `scripts/start-demo.py` now:
1. Checks Wazuh manager (`:55000`) is reachable before starting. The indexer (`:9200`)
   is not exposed to the Windows host — it is Docker-network-internal only. The manager
   health subsumes indexer health.
2. Uses `start_forwarder.py` (loads token) and waits for `:9999` to be open **before**
   starting `start_backend.py`, so the delivery worker never delivers to a closed socket.

**No requeue path exists.** Dead-lettered events cannot be replayed; this is expected
behaviour documented in `audit/outbox.py`. The events are visible in the Overview
panel as a count. Do not delete them — they are the audit record.

### Forwarder start order (delivery worker dead-letters)

Always start services in this order:
1. `docker compose up -d` (Wazuh stack — wait for manager `:55000` healthy)
2. `start_forwarder.py` or `start-demo.py` — forwarder MUST be listening on `:9999`
3. `start_backend.py` — delivery worker enabled; it starts delivering immediately

**Note:** The indexer (`:9200`) is Docker-network-internal only — not accessible from
Windows. Use `:55000` (manager API) to verify the stack is ready.

If the backend starts before the forwarder, every delivery attempt hits a refused
connection. After 10 retries (exponential backoff, up to 1-hour max), the event
becomes a dead letter. Use `start-demo.py` (updated) to enforce this order.

---

## Directory Structure

```
deploy/wazuh/
├── .env.example               password template (never commit .env)
├── docker-compose.yml         Wazuh single-node + PostgreSQL 15 (SSL)
├── setup-wsl.sh               WSL2 bootstrap (Docker + compose up)
├── import_dashboard.sh        idempotent dashboard importer (see Dashboards section)
├── README.md                  this file
├── agent/
│   └── ossec-localfile.conf   Windows agent config fragment
├── dashboards/
│   └── finsentinel.ndjson     saved-objects export (index pattern + 4 vizs + dashboard)
├── decoders/
│   └── finsentinel.xml        JSON decoder (prematch: {"timestamp":)
└── rules/
    └── finsentinel_rules.xml  30 custom rules, IDs 100100-100140
```
