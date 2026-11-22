"""GET /api/v1/vapt-report — read the pre-built VAPT summary snapshot."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter, Depends

from api._auth import require_operator_auth

logger = logging.getLogger(__name__)

router = APIRouter()

_SUMMARY_PATH = Path("artifacts/vapt_summary.json")
_MAX_BYTES = 128 * 1024  # 128 KB hard cap
_WHITELISTED_KEYS = frozenset(
    {
        "run",
        "timestamp",
        "target",
        "summary",
        "categories",
        "findings",
        "generated_at",
    }
)


@router.get("/vapt-report")
def get_vapt_report(
    _: None = Depends(require_operator_auth),
) -> dict:
    """Return the VAPT summary snapshot (artifacts/vapt_summary.json)."""
    if not _SUMMARY_PATH.exists():
        return {
            "available": False,
            "message": "VAPT summary not built yet. Run scripts/build_vapt_summary.py.",
        }

    try:
        size = _SUMMARY_PATH.stat().st_size
        if size > _MAX_BYTES:
            return {"available": False, "message": "VAPT summary file is unexpectedly large."}
        raw = _SUMMARY_PATH.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Cannot read vapt_summary.json: %s", exc)
        return {"available": False, "message": "Could not read VAPT summary."}

    if not isinstance(data, dict):
        return {"available": False, "message": "Unexpected VAPT summary format."}

    # Strip any keys not in the whitelist before returning
    out = {k: v for k, v in data.items() if k in _WHITELISTED_KEYS}
    out["available"] = True
    return out
