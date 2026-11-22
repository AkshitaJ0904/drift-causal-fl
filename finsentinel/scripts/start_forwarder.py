"""Start the FinSentinel SIEM forwarder.

Reads FINSENTINEL_AUDIT_WEBHOOK_TOKEN from ~/.finsentinel/dev_token.txt
and injects it into the environment before importing siem_forwarder.
Token is never printed to the console.

Usage (from finsentinel/ directory):
    .\\venv-security\\Scripts\\python.exe scripts\\start_forwarder.py
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

os.environ.setdefault("FINSENTINEL_AUDIT_WEBHOOK_TOKEN", token)
os.environ.setdefault("FINSENTINEL_SIEM_LOG", "logs/finsentinel-siem.jsonl")
os.environ.setdefault("FINSENTINEL_FORWARDER_PORT", "9999")

# Change to repo root so relative log path resolves correctly
os.chdir(Path(__file__).parent.parent)

# Import and run the forwarder directly (same process, no subprocess)
spec = importlib.util.spec_from_file_location(
    "siem_forwarder", Path(__file__).parent / "siem_forwarder.py"
)
if spec is None or not isinstance(spec.loader, importlib.abc.Loader):
    sys.exit("Error: cannot load siem_forwarder.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
mod.main()  # type: ignore[attr-defined]
