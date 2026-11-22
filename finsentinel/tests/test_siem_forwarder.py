"""Tests for scripts/siem_forwarder.py (local SIEM webhook receiver)."""

from __future__ import annotations

import importlib.util
import json
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from http.server import HTTPServer
from pathlib import Path
from types import ModuleType

import pytest

_TOKEN = "t" * 64
_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "siem_forwarder.py"


@pytest.fixture()
def forwarder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[str, Path]]:
    log = tmp_path / "siem.jsonl"
    monkeypatch.setenv("FINSENTINEL_AUDIT_WEBHOOK_TOKEN", _TOKEN)
    monkeypatch.setenv("FINSENTINEL_SIEM_LOG", str(log))
    spec = importlib.util.spec_from_file_location("siem_forwarder_under_test", _SCRIPT)
    assert spec and spec.loader
    mod: ModuleType = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    server = HTTPServer(("127.0.0.1", 0), mod._Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/ingest", log
    finally:
        server.shutdown()
        server.server_close()


def _post(url: str, body: bytes, token: str | None) -> int:
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    if token is not None:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return int(resp.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)


def _event(key: str = "k1") -> bytes:
    return json.dumps(
        {
            "idempotency_key": key,
            "event_id": 1,
            "service": "finsentinel",
            "event_type": "security.replay_detected",
            "severity": "high",
            "client_id": "c1",
            "update_id": "u1",
            "description": "Update rejected by replay protection.",
            "created_at": "2026-11-20T00:00:00",
        }
    ).encode()


def _lines(log: Path) -> list[dict[str, object]]:
    if not log.exists():
        return []
    return [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines() if x]


def test_valid_token_writes_record(forwarder: tuple[str, Path]) -> None:
    url, log = forwarder
    assert _post(url, _event(), _TOKEN) == 200
    rows = _lines(log)
    assert len(rows) == 1
    assert rows[0]["source"] == "finsentinel"
    assert rows[0]["event_type"] == "security.replay_detected"


def test_missing_token_rejected(forwarder: tuple[str, Path]) -> None:
    url, log = forwarder
    assert _post(url, _event(), None) == 401
    assert _lines(log) == []


def test_wrong_token_rejected(forwarder: tuple[str, Path]) -> None:
    url, log = forwarder
    assert _post(url, _event(), "x" * 64) == 401
    assert _lines(log) == []


def test_duplicate_idempotency_key_written_once(forwarder: tuple[str, Path]) -> None:
    url, log = forwarder
    assert _post(url, _event("dup"), _TOKEN) == 200
    assert _post(url, _event("dup"), _TOKEN) == 200
    assert len(_lines(log)) == 1


def test_invalid_json_rejected(forwarder: tuple[str, Path]) -> None:
    url, log = forwarder
    assert _post(url, b"{not json", _TOKEN) == 400
    assert _post(url, b"[1, 2]", _TOKEN) == 400
    assert _lines(log) == []


def test_missing_idempotency_key_rejected(forwarder: tuple[str, Path]) -> None:
    url, log = forwarder
    assert _post(url, json.dumps({"event_type": "x"}).encode(), _TOKEN) == 400
    assert _lines(log) == []
