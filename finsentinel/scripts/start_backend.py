"""Start the FinSentinel backend with the SIEM delivery worker enabled.

Reads FINSENTINEL_AUDIT_WEBHOOK_TOKEN from ~/.finsentinel/dev_token.txt
and sets it in the environment.  Token is never printed to the console.
The delivery worker forwards audit events to the SIEM forwarder on :9999.

Usage (from finsentinel/ directory, after starting start_forwarder.py):
    .\\venv-security\\Scripts\\python.exe scripts\\start_backend.py
"""

import importlib.abc
import importlib.util
import os
import sys
from pathlib import Path

TOKEN_FILE = Path.home() / ".finsentinel" / "dev_token.txt"
if not TOKEN_FILE.exists():
    sys.exit(f"Error: token file not found: {TOKEN_FILE}\nRun scripts/run_dev.py once first.")

token = TOKEN_FILE.read_text().strip()
if len(token) < 32:
    sys.exit("Error: token file is too short — regenerate it by running scripts/run_dev.py")

# Set SIEM delivery worker env vars BEFORE importing run_dev (which uses os.environ.setdefault)
os.environ["FINSENTINEL_AUDIT_WEBHOOK_TOKEN"]          = token
os.environ["FINSENTINEL_AUDIT_WEBHOOK_URL"]            = "http://127.0.0.1:9999/ingest"
os.environ["FINSENTINEL_AUDIT_DELIVERY_WORKER_ENABLED"] = "1"
os.environ.setdefault("FINSENTINEL_SIEM_LOG", "logs/finsentinel-siem.jsonl")

# Change to repo root so relative paths in run_dev.py work
os.chdir(Path(__file__).parent.parent)

# Run the dev server (run_dev.py sets remaining env vars and starts uvicorn)
spec = importlib.util.spec_from_file_location(
    "run_dev", Path(__file__).parent / "run_dev.py"
)
if spec is None or not isinstance(spec.loader, importlib.abc.Loader):
    sys.exit("Error: cannot load run_dev.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
