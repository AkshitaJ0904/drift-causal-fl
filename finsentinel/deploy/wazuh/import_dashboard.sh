#!/bin/bash
# Import (or re-import) the FinSentinel Security Overview dashboard.
# Idempotent: safe to run multiple times. Existing objects are overwritten.
#
# Usage (from deploy/wazuh/ inside WSL2):
#   INDEXER_PASSWORD=<password> bash import_dashboard.sh
#   OR source ~/finsentinel-wazuh/.env && bash import_dashboard.sh
#
# Credentials: local-dev default, see ~/finsentinel-wazuh/.env
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NDJSON="${SCRIPT_DIR}/dashboards/finsentinel.ndjson"
DASHBOARD_URL="${DASHBOARD_URL:-https://localhost:443}"
: "${INDEXER_PASSWORD:?INDEXER_PASSWORD must be set (see ~/finsentinel-wazuh/.env)}"

if [[ ! -f "$NDJSON" ]]; then
  echo "ERROR: $NDJSON not found" >&2
  exit 1
fi

echo "[import] Importing FinSentinel Security Overview dashboard..."
HTTP_STATUS=$(curl -sk -w "%{http_code}" -o /tmp/import_response.json \
  -u "admin:${INDEXER_PASSWORD}" \
  -X POST "${DASHBOARD_URL}/api/saved_objects/_import?overwrite=true" \
  -H "osd-xsrf: true" \
  --form "file=@${NDJSON};type=application/ndjson" 2>/dev/null)

if [[ "$HTTP_STATUS" -eq 200 ]]; then
  SUCCESS=$(python3 -c "import json,sys; d=json.load(open('/tmp/import_response.json')); print(d.get('success','?'), 'successes:', d.get('successCount',0))" 2>/dev/null || echo "unknown")
  echo "[import] OK (HTTP $HTTP_STATUS) — $SUCCESS"
else
  echo "[import] FAILED (HTTP $HTTP_STATUS)" >&2
  cat /tmp/import_response.json >&2
  exit 1
fi

echo "[import] Dashboard available at: ${DASHBOARD_URL}/app/dashboards"
