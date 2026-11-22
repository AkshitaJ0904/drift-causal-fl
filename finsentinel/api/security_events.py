"""GET /api/v1/security-events — read recent SIEM events from the JSONL log."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from fastapi import APIRouter, Depends, Query, Request

from api._auth import require_operator_auth
from core.event_mapping import (
    CATALOG_EXTRAS,
    all_exact_mappings,
    level_to_severity,
    lookup,
    prefix_mappings,
)

logger = logging.getLogger(__name__)

router = APIRouter()

_WHITELISTED_FIELDS = frozenset(
    {"timestamp", "event_type", "client_id", "update_id", "service", "event_id", "reason"}
)
_MAX_LIMIT = 200
_READ_BYTES = 256 * 1024  # 256 KB tail read


def _siem_log_path() -> Path | None:
    """Return the SIEM log path from env, or None if not set."""
    val = os.environ.get("FINSENTINEL_SIEM_LOG", "").strip()
    if not val:
        return None
    return Path(val)


def _read_tail(path: Path, max_bytes: int) -> list[str]:
    """Return the last ``max_bytes`` of a file as a list of lines (oldest first)."""
    size = path.stat().st_size
    offset = max(0, size - max_bytes)
    with path.open("rb") as fh:
        fh.seek(offset)
        raw = fh.read()
    # Drop a potentially truncated first line when we seeked mid-file.
    text = raw.decode("utf-8", errors="replace")
    lines = text.splitlines()
    if offset > 0 and lines:
        lines = lines[1:]
    return lines


def _parse_event(line: str) -> dict | None:
    """Parse one JSONL line; return whitelisted fields only, or None on error."""
    line = line.strip()
    if not line:
        return None
    try:
        raw = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(raw, dict):
        return None
    out: dict = {}
    for field in _WHITELISTED_FIELDS:
        if field in raw:
            out[field] = raw[field]
    # Enrich with mapping metadata.
    event_type = raw.get("event_type", "")
    meta = lookup(event_type)
    if meta:
        out["rule_id"] = meta["rule_id"]
        out["level"] = meta["level"]
        out["severity"] = meta["severity"]
        out["plain_english"] = meta["plain_english"]
    else:
        out["rule_id"] = None
        out["level"] = None
        out["severity"] = "Unknown"
        out["plain_english"] = event_type
    return out


@router.get("/security-events")
def get_security_events(
    request: Request,
    limit: int = Query(default=50, ge=1, le=_MAX_LIMIT),
    _: None = Depends(require_operator_auth),
) -> dict:
    path = _siem_log_path()

    if path is None:
        return {"events": [], "message": "FINSENTINEL_SIEM_LOG is not configured.", "total": 0}

    if not path.exists():
        return {"events": [], "message": f"SIEM log not found: {path.name}", "total": 0}

    try:
        lines = _read_tail(path, _READ_BYTES)
    except OSError as exc:
        logger.warning("Cannot read SIEM log %s: %s", path, exc)
        return {"events": [], "message": "Could not read SIEM log.", "total": 0}

    events: list[dict] = []
    for line in lines:
        parsed = _parse_event(line)
        if parsed is not None:
            events.append(parsed)

    # Newest first; apply limit.
    events.reverse()
    events = events[:limit]

    return {"events": events, "total": len(events), "message": ""}


@router.get("/security-events/catalog")
def get_security_events_catalog(
    _: None = Depends(require_operator_auth),
) -> dict:
    """Return every detection rule in the mapping (read-only, no secrets)."""
    def _enrich(row: dict) -> dict:
        extra = CATALOG_EXTRAS.get(row["rule_id"], {})
        row["why_it_matters"] = extra.get("why_it_matters", "")
        row["what_to_do"] = extra.get("what_to_do", "")
        row["example"] = extra.get("example", "")
        return row

    rows: list[dict] = []
    for event_type, meta in all_exact_mappings().items():
        rows.append(_enrich({
            "event_type": event_type,
            "rule_id": meta["rule_id"],
            "level": meta["level"],
            "severity": meta["severity"],
            "plain_english": meta["plain_english"],
            "match_type": "exact",
        }))
    for prefix, meta in prefix_mappings():
        rows.append(_enrich({
            "event_type": prefix + "*",
            "rule_id": meta["rule_id"],
            "level": meta["level"],
            "severity": meta["severity"],
            "plain_english": meta["plain_english"],
            "match_type": "prefix",
        }))
    # Rule 100140 is a Wazuh-side brute-force correlation rule (level 13 → Critical)
    rows.append(_enrich({
        "event_type": "(wazuh-correlation)",
        "rule_id": "100140",
        "level": 13,
        "severity": level_to_severity(13),
        "plain_english": "Brute-force operator-auth detected (Wazuh correlation, ≥5 failures/60 s)",  # noqa: E501
        "match_type": "correlation",
    }))
    rows.sort(key=lambda r: r["rule_id"])
    return {"rules": rows, "total": len(rows)}
