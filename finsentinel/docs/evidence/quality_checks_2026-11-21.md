# Quality Check Results — 2026-11-21

All checks run on branch `JaivardhanVajpai`, working directory
`D:\prj 4\drift-causal-fl\finsentinel`.

## Backend (Python)

| Check | Result | Detail |
|-------|--------|--------|
| ruff (linter) | **PASS — 0 errors** | Fixed E501 in `scripts/demo_aggregation.py:191` |
| mypy (type check) | **PASS — 0 issues** | `scripts/start-demo.py`, `scripts/demo_aggregation.py` |
| pytest (SQLite mode) | **PASS — 754 passed, 3 skipped** | 3 skipped = PG concurrent tests (env vars not set in Windows SQLite mode) |

## Frontend (TypeScript / Vite)

| Check | Result | Detail |
|-------|--------|--------|
| vitest | **PASS — 94 passed** | 10 test files, ~4s |
| tsc --noEmit | **PASS — 0 errors** | TypeScript strict mode |
| vite build | **PASS** | 40 modules, 465ms; output: `dist/index.html`, `dist/assets/index-*.css`, `dist/assets/index-*.js` |

## Git status

```
M AGENTref.md
 M conftest.py
?? CLAUDE_HANDOVER.md
?? CODEX_HANDOVER.md
?? IMPLEMENTATION_STATUS.md
?? deploy/
?? finsentinel_dev.db
?? logs/
?? scripts/demo_aggregation.py
?? scripts/demo_payloads.json
?? scripts/demo_submit_updates.py
?? scripts/demo_wazuh_events.py
?? scripts/run_dev.py
?? scripts/seed_demo_data.py
?? scripts/siem_forwarder.py
?? scripts/start-demo.py
?? scripts/start_backend.ps1
?? scripts/start_backend.py
?? scripts/start_forwarder.ps1
?? scripts/start_forwarder.py
?? tests/test_siem_forwarder.py
```

AGENTref.md and conftest.py are modified (expected — session work).
No unintended changes to tracked files. No commit made (per security rules).

## Stack health at time of checks (2026-11-21 ~17:25 UTC)

| Container | Status |
|-----------|--------|
| wazuh-manager | Up, **healthy** |
| wazuh-indexer | Up, **healthy** |
| finsentinel-postgres | Up, **healthy** |
| wazuh-dashboard | Up 15 min, **starting** (600s start_period + 20×30s retries = up to 20 min window) |

OpenSearch cluster: **green**, 86 total alert docs across 2 daily indices.
