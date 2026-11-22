"""Start the FinSentinel demo stack: SIEM forwarder, backend, frontend.

Run from the finsentinel/ directory:
    .\\venv-security\\Scripts\\python.exe scripts\\start-demo.py

Idempotent: if a service is already running on its port the script reuses
it and does not start a duplicate.  Restart only the processes this script
itself started (tracked in the ``procs`` list).

Pre-flight checks (aborts with a clear message if either fails):
  1. Wazuh manager (:55000) and indexer (:9200) must be reachable.
  2. SIEM forwarder (:9999) must be listening before the backend starts,
     so the delivery worker never delivers to a closed port.

Starts three processes in order (skips if port already in use):
  1. start_forwarder.py  — loads token, starts webhook receiver on :9999
  2. start_backend.py    — loads token, starts FastAPI + delivery worker on :8000
  3. npm run dev         — Vite frontend on :5173

After all services are ready, opens two browser tabs:
  - http://localhost:5173  (FinSentinel operator UI)
  - https://localhost      (Wazuh dashboard — accept the self-signed cert)

Press Ctrl-C to stop all three.
"""

import signal
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

HERE = Path(__file__).parent.parent
PYTHON = Path(sys.executable)
NPM = "npm.cmd" if sys.platform == "win32" else "npm"

# Use the wrapper scripts so the token is loaded and delivery-worker env var is set.
FORWARDER_CMD = [str(PYTHON), str(HERE / "scripts" / "start_forwarder.py")]
BACKEND_CMD = [str(PYTHON), str(HERE / "scripts" / "start_backend.py")]
FRONTEND_CMD = [NPM, "run", "dev"]
FRONTEND_CWD = HERE / "frontend"

procs: list[subprocess.Popen] = []


def stop_all() -> None:
    for p in procs:
        try:
            p.terminate()
        except OSError:
            pass
    for p in procs:
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()


def _port_open(host: str, port: int) -> bool:
    """Return True if something is accepting connections on host:port."""
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


def _wait_for_port(host: str, port: int, label: str, timeout: int = 30) -> None:
    """Block until host:port is reachable, then return; abort on timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _port_open(host, port):
            print(f"[start-demo]   {label} ready on :{port}")
            return
        time.sleep(1)
    sys.exit(
        f"[start-demo] ABORT: {label} did not answer on :{port} within {timeout}s.\n"
        "  Start Wazuh first:  cd deploy/wazuh && docker compose --env-file "
        "~/finsentinel-wazuh/.env up -d"
    )


def _docker_health(container: str) -> str:
    """Return the Docker health status string for a container name, or '' on error.

    Runs via WSL on Windows so we can reach the Docker daemon without exposing
    internal ports (the indexer :9200 is not mapped to the Windows host).
    """
    if sys.platform != "win32":
        cmd = ["docker", "inspect", container,
               "--format", "{{.State.Health.Status}}"]
    else:
        cmd = ["wsl", "-e", "bash", "-c",
               f"docker inspect {container} --format '{{{{.State.Health.Status}}}}'"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return result.stdout.strip()
    except Exception:
        return ""


def _preflight() -> None:
    """Abort unless both Wazuh manager (:55000) and indexer are healthy.

    Checks in order:
      1. TCP :55000 reachable from Windows (manager API port).
      2. wazuh-indexer Docker health == 'healthy' (security plugin ready).
      3. wazuh-manager Docker health == 'healthy' (filebeat + API ready).

    The indexer and manager health are verified via 'docker inspect' run through
    WSL, since :9200 is not exposed to the Windows host.
    """
    print("[start-demo] Pre-flight: Wazuh manager API (:55000) ...")
    if not _port_open("127.0.0.1", 55000):
        sys.exit(
            "[start-demo] ABORT: Wazuh manager API not reachable on :55000.\n"
            "  Run:  cd deploy/wazuh && docker compose --env-file "
            "~/finsentinel-wazuh/.env up -d"
        )
    print("[start-demo]   Wazuh manager (:55000) OK.")

    print("[start-demo] Pre-flight: Wazuh indexer Docker health ...")
    indexer_health = _docker_health("wazuh-indexer")
    if indexer_health != "healthy":
        sys.exit(
            f"[start-demo] ABORT: wazuh-indexer health is '{indexer_health}' (need 'healthy').\n"
            "  Wait for Docker healthcheck to pass or run:\n"
            "  cd deploy/wazuh && docker compose --env-file ~/finsentinel-wazuh/.env up -d"
        )
    print("[start-demo]   wazuh-indexer healthy.")

    print("[start-demo] Pre-flight: Wazuh manager Docker health ...")
    manager_health = _docker_health("wazuh-manager")
    if manager_health != "healthy":
        sys.exit(
            f"[start-demo] ABORT: wazuh-manager health is '{manager_health}' (need 'healthy').\n"
            "  Wait for Docker healthcheck to pass or run:\n"
            "  cd deploy/wazuh && docker compose --env-file ~/finsentinel-wazuh/.env up -d"
        )
    print("[start-demo]   wazuh-manager healthy.")


def main() -> None:
    _preflight()

    # SIEM forwarder (:9999) — skip if already running.
    if _port_open("127.0.0.1", 9999):
        print("[start-demo] SIEM forwarder already running on :9999 — reusing.")
    else:
        print("[start-demo] Starting SIEM forwarder on :9999 ...")
        procs.append(subprocess.Popen(FORWARDER_CMD))
        # Wait for :9999 before starting the backend so the delivery worker never
        # sends to a closed socket (which causes dead-letters after 10 retries).
        _wait_for_port("127.0.0.1", 9999, "SIEM forwarder")

    # Backend (:8000) — skip if already running.
    if _port_open("127.0.0.1", 8000):
        print("[start-demo] Backend already running on :8000 — reusing.")
    else:
        print("[start-demo] Starting backend on :8000 (delivery worker enabled) ...")
        procs.append(subprocess.Popen(BACKEND_CMD))
        time.sleep(2)

    # Frontend (:5173) — skip if already running.
    if _port_open("127.0.0.1", 5173):
        print("[start-demo] Frontend already running on :5173 — reusing.")
    else:
        print("[start-demo] Starting frontend on :5173 ...")
        procs.append(
            subprocess.Popen(FRONTEND_CMD, cwd=str(FRONTEND_CWD), shell=False)
        )
        _wait_for_port("127.0.0.1", 5173, "Frontend", timeout=60)

    # Open browser tabs.
    print("[start-demo] Opening browser tabs ...")
    webbrowser.open("http://localhost:5173")
    time.sleep(1)
    webbrowser.open("https://localhost")

    print("[start-demo] All services ready.")
    print("[start-demo]   FinSentinel UI : http://localhost:5173")
    print("[start-demo]   Wazuh dashboard: https://localhost  (accept the self-signed cert)")
    print("[start-demo] Press Ctrl-C to stop processes started by this script.")
    try:
        while True:
            for p in procs:
                if p.poll() is not None:
                    args = p.args
                    cmd = args[0] if isinstance(args, (list, tuple)) else str(args)
                    print(f"[start-demo] Process {cmd!r} exited ({p.returncode})")
            time.sleep(2)
    except KeyboardInterrupt:
        print("\n[start-demo] Stopping processes started by this script ...")
        stop_all()
        print("[start-demo] Done.")


if __name__ == "__main__":
    if sys.platform == "win32":
        signal.signal(signal.SIGBREAK, lambda *_: stop_all())
    main()
