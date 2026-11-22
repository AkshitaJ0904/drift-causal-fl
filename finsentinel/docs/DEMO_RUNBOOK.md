# FinSentinel Phase 3 Demo Runbook

## Start command

```
.\venv-security\Scripts\python.exe scripts\start-demo.py
```

Run from the `finsentinel/` directory.  Pre-requisite: Wazuh containers healthy
(`wazuh-manager`, `wazuh-indexer`, `wazuh-dashboard`, `finsentinel-postgres`).

## Two URLs

| URL | Purpose |
|-----|---------|
| `http://localhost:5173` | FinSentinel operator UI |
| `https://localhost` | Wazuh dashboard (accept the self-signed cert) |

The start script opens both tabs automatically.

## Wazuh cert warning

Browser shows "Your connection is not private" for `https://localhost`.
Click **Advanced → Proceed to localhost** (Chrome/Edge) or **Accept the Risk** (Firefox).
Credentials: local-dev default, see `~/finsentinel-wazuh/.env`.

## 7-minute demo script (Phase 3)

**1 — Dashboard security posture strip (30 s)**

Navigate to `http://localhost:5173` and log in with the operator token.
The **Dashboard** now shows a **Security Posture** strip at the top:
pass rate (66/70 = 94 %), open findings count (6), and the VAPT run ID (`900be0`).
Point out that this is live data from `artifacts/vapt_summary.json` — no manual copy-paste.

**2 — Generate events (1 min)**

```
.\venv-security\Scripts\python.exe scripts\demo_wazuh_events.py
```

11 attack scenarios run automatically.  Events appear in `logs/finsentinel-siem.jsonl`.

**3 — Security Center: Live Events tab (30 s)**

Navigate to **Security Center** in the sidebar.
The **Live Events** tab shows recent events with Time, Severity badge, description,
client name, and Wazuh rule number.  Page auto-refreshes every 10 s.
Click **Open in Wazuh ↗** to show the Wazuh dashboard side by side.

**4 — Security Center: Detection Rules tab (30 s)**

Click **Detection Rules**.  The table shows all 28 Wazuh rules (26 exact + 1 prefix + rule 100140 labelled as Wazuh correlation, Critical/level 13).  Sorted by rule ID.  Level and severity badge visible for each.

**5 — Security Center: VAPT Report tab (1 min)**

Click **VAPT Report**.  Show:
- Summary strip: 70 tests, 66 PASS, 94 % pass rate, run 900be0
- Category breakdown table (C1–C10)
- 6 findings: 3 Medium (F-01..F-03, confirmed by test FAILs) + 3 Low (F-04..F-06, source-analysis)

Explain that the backend serves `artifacts/vapt_summary.json` — a whitelist-filtered, size-bounded read-only endpoint (`GET /api/v1/vapt-report`).

**6 — Approval decision (1 min)**

Go to **Approvals** in the FinSentinel UI.
Find updates from the demo (client `bank-mumbai-*` or `bank-delhi-*`).
Approve, reject, or quarantine one — provide a reason.
Return to **Security Center → Live Events**: the `operator.*` events appear within 10–30 s.

**7 — Wazuh dashboard (1 min)**

Open `https://localhost`.  Navigate to **Dashboards → FinSentinel Security Overview**.
Four panels show: severity distribution, alerts over time, top attack types,
and a recent-alerts table with client_id.

**Note — Health Monitor shows "Degraded" (expected)**

The operator dashboard's Health Monitor reports **Degraded** because `outbox.dead_letter_count = 25`.
These 25 events were dead-lettered during run 37dfac when the forwarder was down and the outbox
exhausted all 10 retry attempts.  There is no automatic requeue path (roadmap item); they do not
affect the current demo data or run 900be0 results.

**Bonus — Brute-force scenario (if time allows)**

The demo already sends 5 consecutive `security.signature_verification_failed` events
from one client (scenario S11 × 5).  In Wazuh, search for rule 100140 (level 13,
MITRE T1110).  One Critical alert appears ≈ 60 s after the demo finishes.

## Stack recovery

If the Wazuh stack is unresponsive or containers stopped:

```bash
# From WSL:
cd ~/finsentinel-wazuh   # or:  cd /mnt/d/prj\ 4/drift-causal-fl/finsentinel/deploy/wazuh
docker compose --env-file ~/finsentinel-wazuh/.env down
docker compose --env-file ~/finsentinel-wazuh/.env up -d
```

Wait ~30 s for `wazuh-indexer` and `wazuh-manager` to become healthy, then re-run
`start-demo.py`.  See `docs/DEMO_RECOVERY.md` for detailed troubleshooting.
