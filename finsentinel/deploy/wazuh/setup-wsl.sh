#!/usr/bin/env bash
# FinSentinel WSL2 bootstrap: Docker Engine + Wazuh 4.8.2 single-node + test PostgreSQL.
# LOCAL DEV ONLY - all ports bound to 127.0.0.1.
#
#   cd "/mnt/d/prj 4/drift-causal-fl/finsentinel/deploy/wazuh"
#   bash setup-wsl.sh
#
# Safe to re-run: never overwrites an existing ~/finsentinel-wazuh/.env,
# never regenerates existing certificates, never deletes volumes.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_DIR="$HOME/finsentinel-wazuh"
ENV_FILE="$ENV_DIR/.env"

echo "=== FinSentinel WSL2 bootstrap (Wazuh 4.8.2) ==="

# 1. Docker Engine (official Docker apt repository)
if ! command -v docker &>/dev/null; then
  echo "[docker] Installing Docker Engine..."
  sudo apt-get update -qq
  sudo apt-get install -y ca-certificates curl gnupg
  sudo install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    | sudo gpg --dearmor --yes -o /etc/apt/keyrings/docker.gpg
  sudo chmod a+r /etc/apt/keyrings/docker.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
  sudo apt-get update -qq
  sudo apt-get install -y docker-ce docker-ce-cli containerd.io \
    docker-buildx-plugin docker-compose-plugin
  sudo usermod -aG docker "$USER"
else
  echo "[docker] Already installed."
fi

# Start the daemon if needed
if ! sudo docker info &>/dev/null; then
  sudo service docker start
  sleep 3
fi

# Group membership only applies to new logins; fall back to sudo in this run.
if docker info &>/dev/null; then DOCKER="docker"; else DOCKER="sudo docker"; fi
echo "[docker] Using: $DOCKER"

# 2. Kernel setting required by the Wazuh indexer (OpenSearch)
if [ "$(sysctl -n vm.max_map_count)" -lt 262144 ]; then
  echo "[sysctl] vm.max_map_count=262144"
  sudo sysctl -w vm.max_map_count=262144
  echo "vm.max_map_count=262144" | sudo tee /etc/sysctl.d/99-wazuh.conf >/dev/null
fi

# 3. .env outside the repo (never overwritten once created)
mkdir -p "$ENV_DIR"
if [ ! -f "$ENV_FILE" ]; then
  echo "[env] Creating $ENV_FILE (chmod 600)"
  cp "$SCRIPT_DIR/.env.example" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
fi
if grep -q '^POSTGRES_PASSWORD=__GENERATE__' "$ENV_FILE"; then
  PGPW="$(openssl rand -hex 24)"
  sed -i "s/^POSTGRES_PASSWORD=__GENERATE__/POSTGRES_PASSWORD=${PGPW}/" "$ENV_FILE"
  echo "[env] Generated a random PostgreSQL test password (stored only in $ENV_FILE)."
fi

# 4. SIEM log directory (written by scripts/siem_forwarder.py on Windows)
SIEM_DIR="$(grep -E '^FINSENTINEL_LOGS_DIR=' "$ENV_FILE" | cut -d= -f2- || true)"
SIEM_DIR="${SIEM_DIR:-/tmp/finsentinel-logs}"
mkdir -p "$SIEM_DIR"
touch "$SIEM_DIR/finsentinel-siem.jsonl"
echo "[siem] Log directory: $SIEM_DIR"

cd "$SCRIPT_DIR"

# 5. TLS certificates (indexer refuses to start without them)
if [ -f "$SCRIPT_DIR/config/wazuh_indexer_ssl_certs/root-ca.pem" ]; then
  echo "[certs] Already present - skipping."
else
  echo "[certs] Generating Wazuh TLS certificates..."
  $DOCKER compose -f generate-indexer-certs.yml run --rm generator
fi

# 6. Copy config/cert files to Linux filesystem with strict permissions.
#    This prevents the OpenSearch security plugin from seeing 0777 drvfs files
#    and triggering a full JDK scan that OOMs the container.
CONFIG_DST="$ENV_DIR/config"
mkdir -p "$CONFIG_DST/wazuh_indexer_ssl_certs" "$CONFIG_DST/wazuh_indexer" \
         "$CONFIG_DST/wazuh_dashboard" "$CONFIG_DST/wazuh_cluster"
cp "$SCRIPT_DIR/config/wazuh_indexer_ssl_certs/"*.pem "$CONFIG_DST/wazuh_indexer_ssl_certs/"
cp "$SCRIPT_DIR/config/wazuh_indexer/"*.yml          "$CONFIG_DST/wazuh_indexer/"
cp "$SCRIPT_DIR/config/wazuh_dashboard/"*.yml         "$CONFIG_DST/wazuh_dashboard/"
cp "$SCRIPT_DIR/config/wazuh_cluster/wazuh_manager.conf" "$CONFIG_DST/wazuh_cluster/"
# Cert/key files must be 0600 so the OpenSearch security plugin doesn't OOM-scan the JDK.
chmod 0600 "$CONFIG_DST/wazuh_indexer_ssl_certs/"*.pem
chmod 0600 "$CONFIG_DST/wazuh_indexer/"*.yml
chmod 0600 "$CONFIG_DST/wazuh_dashboard/"*.yml
# ossec.conf must NOT be 0600: the init script copies it as root:root, so 0600 makes it
# unreadable by the wazuh user (analysisd) → CRITICAL error 1226.  0644 is correct.
chmod 0644 "$CONFIG_DST/wazuh_cluster/wazuh_manager.conf"
echo "[config] Synced to $CONFIG_DST with 0600 permissions."

# Write WAZUH_CONFIG_DIR to .env if not already there
if ! grep -q '^WAZUH_CONFIG_DIR=' "$ENV_FILE"; then
  echo "WAZUH_CONFIG_DIR=$CONFIG_DST" >> "$ENV_FILE"
  echo "[env] Added WAZUH_CONFIG_DIR=$CONFIG_DST"
fi

# 7. Start the stack
echo "[compose] Pulling images and starting containers (first run: 10-30 min)..."
$DOCKER compose --env-file "$ENV_FILE" up -d

# 8. Bootstrap wazuh_etc shared dir (chicken-and-egg fix):
#    analysisd reads etc/shared/ar.conf at startup, but that file is only created
#    by a SUCCESSFUL first start of analysisd.  On a fresh volume it doesn't exist,
#    so analysisd crashes before it can create it.  We pre-create it here.
echo "[wazuh-etc] Waiting 10s for manager container to initialise..."
sleep 10
echo "[wazuh-etc] Bootstrapping /var/ossec/etc/shared/ar.conf ..."
$DOCKER compose --env-file "$ENV_FILE" exec -T wazuh.manager bash -c \
  'mkdir -p /var/ossec/etc/shared/default \
   && touch /var/ossec/etc/shared/ar.conf \
   && chown -R root:wazuh /var/ossec/etc/shared \
   && chmod 770 /var/ossec/etc/shared \
   && chmod 660 /var/ossec/etc/shared/ar.conf \
   && echo "ar.conf ok"' \
  || echo "[wazuh-etc] Container not ready yet — ar.conf will be created on next start."
# Restart manager so analysisd picks up ar.conf and ossec.conf (now 0644).
echo "[wazuh-etc] Restarting manager so analysisd can start with ar.conf present..."
$DOCKER compose --env-file "$ENV_FILE" restart wazuh.manager

echo ""
echo "=== Done. Containers are starting; the dashboard needs 2-5 more minutes. ==="
echo "  Check status : $DOCKER compose --env-file $ENV_FILE ps"
echo "  Dashboard    : https://localhost  (user: admin, local-dev default password)"
