"""Tests for GET /api/v1/vapt-report."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
ENDPOINT = "/api/v1/vapt-report"

TOKEN_ENV = "FINSENTINEL_OPERATOR_TOKEN"
VALID_TOKEN = "a" * 64


@pytest.fixture(autouse=True)
def _set_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(TOKEN_ENV, VALID_TOKEN)


def test_401_without_token() -> None:
    resp = client.get(ENDPOINT, headers={})
    assert resp.status_code == 401


def test_401_with_wrong_token() -> None:
    resp = client.get(ENDPOINT, headers={"Authorization": "Bearer wrongtoken"})
    assert resp.status_code == 401


def test_unavailable_when_summary_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import api.vapt_report as _vr
    monkeypatch.setattr(_vr, "_SUMMARY_PATH", tmp_path / "nonexistent.json")
    resp = client.get(ENDPOINT, headers={"Authorization": f"Bearer {VALID_TOKEN}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is False
    assert "message" in body


def test_returns_whitelisted_fields_only(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import api.vapt_report as _vr

    summary = {
        "run": "abc123",
        "timestamp": "2026-11-21T00:00:00Z",
        "target": "http://127.0.0.1:8001",
        "summary": {"total": 10, "pass": 9, "fail": 1},
        "categories": [],
        "findings": [],
        "generated_at": "2026-11-21T00:00:00+00:00",
        "secret_key": "should_be_stripped",
        "internal_path": "/etc/passwd",
    }
    p = tmp_path / "vapt_summary.json"
    p.write_text(json.dumps(summary), encoding="utf-8")
    monkeypatch.setattr(_vr, "_SUMMARY_PATH", p)

    resp = client.get(ENDPOINT, headers={"Authorization": f"Bearer {VALID_TOKEN}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is True
    assert "run" in body
    assert "summary" in body
    assert "secret_key" not in body
    assert "internal_path" not in body


def test_bounded_file_size(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import api.vapt_report as _vr

    p = tmp_path / "huge.json"
    p.write_bytes(b"x" * (200 * 1024))
    monkeypatch.setattr(_vr, "_SUMMARY_PATH", p)

    resp = client.get(ENDPOINT, headers={"Authorization": f"Bearer {VALID_TOKEN}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is False


def test_invalid_json_handled(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import api.vapt_report as _vr

    p = tmp_path / "bad.json"
    p.write_text("not valid json", encoding="utf-8")
    monkeypatch.setattr(_vr, "_SUMMARY_PATH", p)

    resp = client.get(ENDPOINT, headers={"Authorization": f"Bearer {VALID_TOKEN}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is False
