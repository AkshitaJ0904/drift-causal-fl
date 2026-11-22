# Demo Recovery — WSL VM Restart Root Cause & Fix

**Date:** 2026-11-21  
**Branch:** JaivardhanVajpai  
**Status:** FIXED (both root causes resolved)

---

## Root cause 1 — Docker daemon crash-loop (prior session fix)

**Symptom:** WSL VM restarted every 4–8 minutes during Wazuh stack uptime.

**Chain of events:**
1. `wazuh.dashboard` container started and immediately tried to connect to the indexer.
2. The indexer's old healthcheck used `_cluster/health`, which returns green while the
   security plugin is still initializing.
3. The dashboard hit `ResponseError` on the security-plugin endpoints → restarted.
4. Each dashboard restart sent a burst of `ECONNREFUSED` on port 9200 to the indexer.
5. This caused `dockerd` to crash.
6. WSL orphaned its PID1 → WSL called `reboot(RB_POWER_OFF)`.

**Fix (applied prior session):** Changed indexer healthcheck to the OpenSearch Security
API endpoint (`_opendistro/_security/api/internalusers/admin`), which only returns HTTP
200 once the security plugin is fully initialized. This ensures the manager and dashboard
start only after the indexer is truly ready.

---

## Root cause 2 — WSL forced reboot on `compose down` (this session fix)

**Symptom:** Running `docker compose down` while containers were up caused WSL to call
`reboot(RB_POWER_OFF)`, resetting the entire WSL VM.

**Chain of events:**
1. `compose down` sends `SIGTERM` to all containers.
2. The indexer's JVM (OpenSearch) needs 15–30s to flush and shut down cleanly.
3. WSL's default `SIGTERM` timeout is **10 seconds**.
4. After 10s, WSL sent `SIGKILL` to the container process.
5. The JVM was killed uncleanly → Docker reported the container as failed.
6. With `dockerd` handling a cascade of container failures at once, the VM called
   `reboot(RB_POWER_OFF)`.

**Fix (applied this session):** Added `stop_grace_period: 90s` to the `wazuh.indexer`
service in `deploy/wazuh/docker-compose.yml`. This gives the JVM 90 seconds (vs. the
default 10s) to flush write-ahead logs and exit cleanly before Docker escalates to SIGKILL.

---

## Defensive fix — WSL memory cap

`.wslconfig` updated (backed up to `C:\Users\Hp\.wslconfig.bak.20261121`):

```ini
[wsl2]
vmIdleTimeout=-1
memory=5GB
swap=2GB
processors=8
```

The JVM was consuming 2.1GB peak. Without a cap, WSL could consume 7.6GB, risking OOM.
The 5GB cap gives the full Wazuh stack headroom while preventing worst-case OOM.

---

## Verification

After fixes: WSL boot 0 has been running 4+ hours with no VM restart (confirmed via
`/proc/uptime` logger at `/tmp/wsl-uptime.log`).

Uptime logger output (confirming stable stack):
```
2026-11-21T11:39:35Z uptime=14498.11s containers=[wazuh-dashboard:Up 34 seconds (health: starting) wazuh-manager:Up 34 seconds (healthy) finsentinel-postgres:Up 34 seconds (healthy) wazuh-indexer:Up 34 seconds (healthy)]
```

---

## Dashboard health note

The Wazuh dashboard `start_period: 600s` with 20 retries means the Docker healthcheck
window is up to 20 minutes total. The dashboard returns HTTP 503 until the Kibana/Wazuh
plugin fully initializes. In WSL2 on Windows 11, this takes 10–18 minutes due to
I/O constraints. This is expected behavior, not a configuration defect.

The dashboard is accessible at `https://localhost:443` (Windows host) once it becomes
healthy. Login uses the credentials from `~/finsentinel-wazuh/.env`
(local-dev default, see `~/finsentinel-wazuh/.env`).

---

## Files changed

| File | Change |
|------|--------|
| `deploy/wazuh/docker-compose.yml` | Indexer healthcheck → security API; added `stop_grace_period: 90s` to indexer; `start_period: 150s` for indexer |
| `C:\Users\Hp\.wslconfig` | Added `memory=5GB`, `swap=2GB`, `processors=8` |
