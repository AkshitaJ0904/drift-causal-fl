"""Tests for GET /api/v1/security-events, /catalog, and core/event_mapping.py."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from core.event_mapping import all_exact_mappings, level_to_severity, prefix_mappings

client = TestClient(app)
ENDPOINT = "/api/v1/security-events"
RULES_XML = Path(__file__).parent.parent / "deploy" / "wazuh" / "rules" / "finsentinel_rules.xml"

TOKEN_ENV = "FINSENTINEL_OPERATOR_TOKEN"
SIEM_ENV = "FINSENTINEL_SIEM_LOG"
VALID_TOKEN = "a" * 64  # 64 chars, meets minimum requirement


@pytest.fixture(autouse=True)
def _set_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(TOKEN_ENV, VALID_TOKEN)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def test_401_without_token() -> None:
    resp = client.get(ENDPOINT, headers={})
    assert resp.status_code == 401


def test_401_with_wrong_token() -> None:
    resp = client.get(ENDPOINT, headers={"Authorization": "Bearer wrongtoken"})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# File missing / env var missing
# ---------------------------------------------------------------------------

def test_empty_when_siem_log_env_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(SIEM_ENV, raising=False)
    resp = client.get(ENDPOINT, headers={"Authorization": f"Bearer {VALID_TOKEN}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["events"] == []
    assert "FINSENTINEL_SIEM_LOG" in body["message"]


def test_empty_when_file_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(SIEM_ENV, str(tmp_path / "nonexistent.jsonl"))
    resp = client.get(ENDPOINT, headers={"Authorization": f"Bearer {VALID_TOKEN}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["events"] == []


# ---------------------------------------------------------------------------
# Bounded limit
# ---------------------------------------------------------------------------

def test_limit_applied(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    log = tmp_path / "siem.jsonl"
    events = [{"timestamp": f"2026-01-01T00:00:{i:02d}", "event_type": "key.registered"} for i in range(20)]  # noqa: E501
    log.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    monkeypatch.setenv(SIEM_ENV, str(log))
    resp = client.get(ENDPOINT + "?limit=5", headers={"Authorization": f"Bearer {VALID_TOKEN}"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["events"]) == 5


def test_max_limit_capped(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    resp = client.get(ENDPOINT + "?limit=999", headers={"Authorization": f"Bearer {VALID_TOKEN}"})
    # 422 validation error because 999 > 200
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Malformed line skipped
# ---------------------------------------------------------------------------

def test_malformed_line_skipped(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    log = tmp_path / "siem.jsonl"
    log.write_text(
        'not valid json\n'
        '{"timestamp":"2026-01-01T00:00:01","event_type":"key.registered"}\n'
        '\n',
        encoding="utf-8",
    )
    monkeypatch.setenv(SIEM_ENV, str(log))
    resp = client.get(ENDPOINT, headers={"Authorization": f"Bearer {VALID_TOKEN}"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["events"]) == 1
    assert body["events"][0]["event_type"] == "key.registered"


# ---------------------------------------------------------------------------
# No secret fields leaked
# ---------------------------------------------------------------------------

def test_no_secret_fields_leaked(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    log = tmp_path / "siem.jsonl"
    secret_event = {
        "timestamp": "2026-01-01T00:00:01",
        "event_type": "key.registered",
        "token": "super_secret_token",
        "password": "hunter2",
        "raw_weights": [1.0, 2.0, 3.0],
        "idempotency_key": "abc123",
        "client_id": "bank-test",
    }
    log.write_text(json.dumps(secret_event) + "\n", encoding="utf-8")
    monkeypatch.setenv(SIEM_ENV, str(log))
    resp = client.get(ENDPOINT, headers={"Authorization": f"Bearer {VALID_TOKEN}"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["events"]) == 1
    ev = body["events"][0]
    assert "token" not in ev
    assert "password" not in ev
    assert "raw_weights" not in ev
    assert "idempotency_key" not in ev
    assert ev["client_id"] == "bank-test"


# ---------------------------------------------------------------------------
# Newest first ordering
# ---------------------------------------------------------------------------

def test_newest_first(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    log = tmp_path / "siem.jsonl"
    events = [
        {"timestamp": "2026-01-01T00:00:01", "event_type": "key.registered"},
        {"timestamp": "2026-01-01T00:00:02", "event_type": "security.anomaly_clean"},
        {"timestamp": "2026-01-01T00:00:03", "event_type": "security.update_authenticated"},
    ]
    log.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    monkeypatch.setenv(SIEM_ENV, str(log))
    resp = client.get(ENDPOINT, headers={"Authorization": f"Bearer {VALID_TOKEN}"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["events"]) == 3
    assert body["events"][0]["event_type"] == "security.update_authenticated"
    assert body["events"][2]["event_type"] == "key.registered"


# ---------------------------------------------------------------------------
# Mapping drift test — every rule_id in event_mapping.py must exist in
# finsentinel_rules.xml with the same level.
# ---------------------------------------------------------------------------

def test_mapping_matches_rules_xml() -> None:
    if not RULES_XML.exists():
        pytest.skip(f"Rules XML not found: {RULES_XML}")

    tree = ET.parse(RULES_XML)
    xml_rules: dict[str, int] = {}
    for rule_el in tree.iter("rule"):
        rule_id = rule_el.get("id")
        level = rule_el.get("level")
        if rule_id and level:
            xml_rules[rule_id] = int(level)

    for event_type, meta in all_exact_mappings().items():
        rule_id = meta["rule_id"]
        level = meta["level"]
        assert rule_id in xml_rules, f"rule_id {rule_id} (for {event_type}) not found in rules XML"
        assert xml_rules[rule_id] == level, (
            f"rule {rule_id} level mismatch: mapping says {level}, XML says {xml_rules[rule_id]}"
        )

    for prefix, meta in prefix_mappings():
        rule_id = meta["rule_id"]
        level = meta["level"]
        assert rule_id in xml_rules, f"rule_id {rule_id} (prefix {prefix}) not found in rules XML"
        assert xml_rules[rule_id] == level, (
            f"rule {rule_id} level mismatch: mapping says {level}, XML says {xml_rules[rule_id]}"
        )


# ---------------------------------------------------------------------------
# /catalog endpoint
# ---------------------------------------------------------------------------

CATALOG = "/api/v1/security-events/catalog"


def test_catalog_401_without_token() -> None:
    resp = client.get(CATALOG, headers={})
    assert resp.status_code == 401


def test_catalog_returns_rules() -> None:
    resp = client.get(CATALOG, headers={"Authorization": f"Bearer {VALID_TOKEN}"})
    assert resp.status_code == 200
    body = resp.json()
    assert "rules" in body
    assert "total" in body
    assert body["total"] == len(body["rules"])
    assert body["total"] > 0


def test_catalog_contains_rule_100140() -> None:
    resp = client.get(CATALOG, headers={"Authorization": f"Bearer {VALID_TOKEN}"})
    assert resp.status_code == 200
    rules = resp.json()["rules"]
    ids = [r["rule_id"] for r in rules]
    assert "100140" in ids


def test_catalog_rule_fields() -> None:
    resp = client.get(CATALOG, headers={"Authorization": f"Bearer {VALID_TOKEN}"})
    assert resp.status_code == 200
    for rule in resp.json()["rules"]:
        assert "event_type" in rule
        assert "rule_id" in rule
        assert "level" in rule
        assert "severity" in rule
        assert "plain_english" in rule
        assert "match_type" in rule
        assert "why_it_matters" in rule
        assert "what_to_do" in rule
        assert "example" in rule


def test_catalog_extra_fields_are_strings() -> None:
    """Extra educational fields (why_it_matters, what_to_do, example) must be strings."""
    resp = client.get(CATALOG, headers={"Authorization": f"Bearer {VALID_TOKEN}"})
    assert resp.status_code == 200
    for rule in resp.json()["rules"]:
        assert isinstance(rule["why_it_matters"], str), f"rule {rule['rule_id']}: why_it_matters not str"  # noqa: E501
        assert isinstance(rule["what_to_do"], str), f"rule {rule['rule_id']}: what_to_do not str"
        assert isinstance(rule["example"], str), f"rule {rule['rule_id']}: example not str"


def test_catalog_key_rules_have_extra_fields() -> None:
    """High-severity rules (100104, 100105, 100112, 100140) must have non-empty extras."""
    resp = client.get(CATALOG, headers={"Authorization": f"Bearer {VALID_TOKEN}"})
    assert resp.status_code == 200
    keyed = {r["rule_id"]: r for r in resp.json()["rules"]}
    for rid in ("100104", "100105", "100112", "100140"):
        assert rid in keyed, f"Rule {rid} not found in catalog"
        rule = keyed[rid]
        assert rule["why_it_matters"], f"rule {rid}: why_it_matters is empty"
        assert rule["what_to_do"], f"rule {rid}: what_to_do is empty"
        assert rule["example"], f"rule {rid}: example is empty"


def test_catalog_sorted_by_rule_id() -> None:
    resp = client.get(CATALOG, headers={"Authorization": f"Bearer {VALID_TOKEN}"})
    assert resp.status_code == 200
    ids = [r["rule_id"] for r in resp.json()["rules"]]
    assert ids == sorted(ids)


def test_catalog_severity_matches_xml_level() -> None:
    """Every catalog row: severity == level_to_severity(level); XML level agrees."""
    if not RULES_XML.exists():
        pytest.skip(f"Rules XML not found: {RULES_XML}")

    tree = ET.parse(RULES_XML)
    xml_levels: dict[str, int] = {
        el.get("id"): int(el.get("level", 0))
        for el in tree.iter("rule")
        if el.get("id") and el.get("level")
    }

    resp = client.get(CATALOG, headers={"Authorization": f"Bearer {VALID_TOKEN}"})
    assert resp.status_code == 200
    for row in resp.json()["rules"]:
        rid = row["rule_id"]
        level = row["level"]
        severity = row["severity"]
        expected_sev = level_to_severity(level)
        assert severity == expected_sev, (
            f"rule {rid}: severity={severity!r} but level_to_severity({level})={expected_sev!r}"
        )
        if rid in xml_levels:
            assert xml_levels[rid] == level, (
                f"rule {rid}: catalog level={level}, XML level={xml_levels[rid]}"
            )
