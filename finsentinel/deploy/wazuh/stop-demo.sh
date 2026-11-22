#!/usr/bin/env bash
# Stop the Wazuh demo stack cleanly.
# Run from WSL2: bash deploy/wazuh/stop-demo.sh

set -euo pipefail

COMPOSE_DIR="$(dirname "$0")"

echo "=== Stopping Wazuh demo stack ==="
docker compose -f "$COMPOSE_DIR/docker-compose.yml" down --remove-orphans

echo ""
echo "=== Final container state ==="
docker compose -f "$COMPOSE_DIR/docker-compose.yml" ps

echo ""
echo "=== Done. JSONL and database volumes preserved. ==="
echo "    To remove volumes: docker compose -f deploy/wazuh/docker-compose.yml down -v"
