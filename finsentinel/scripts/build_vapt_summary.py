"""Build artifacts/vapt_summary.json from artifacts/vapt_results.json.

Run once after a VAPT suite run:
    python scripts/build_vapt_summary.py
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RESULTS_PATH = REPO_ROOT / "artifacts" / "vapt_results.json"
SUMMARY_PATH = REPO_ROOT / "artifacts" / "vapt_summary.json"

_FINDING_FIELDS = frozenset({"id", "title", "severity", "owasp", "description", "recommendation"})

# All confirmed security findings (F-01..F-06).  These are the single source of truth
# for findings exported to vapt_summary.json (and thus the Security Center VAPT tab).
# F-01..F-03: confirmed by test FAILs in run 900be0 (C2-01, C2-03/C10-02, C10-03).
# F-04..F-06: source-analysis findings from code review (no failing test).
_CURATED_FINDINGS: list[dict] = [
    {
        "id": "F-01",
        "title": "Operator token brute-force: no rate limit",
        "severity": "Medium",
        "owasp": "API4:2023 Unrestricted Resource Consumption",
        "description": "No HTTP 429 / lockout issued after repeated failed operator-auth attempts.",
        "confirmed_by": "C2-01",
    },
    {
        "id": "F-02",
        "title": "Failed operator auth not emitted to SIEM",
        "severity": "Medium",
        "owasp": "API9:2023 Improper Inventory Management",
        "description": "401 responses on operator endpoints produce no outbox/SIEM audit event.",
        "confirmed_by": "C2-03, C10-02",
    },
    {
        "id": "F-03",
        "title": "Aggregation endpoint not audited in SIEM",
        "severity": "Medium",
        "owasp": "API9:2023 Improper Inventory Management",
        "description": "The /api/v1/aggregation/run endpoint emits no audit event.",
        "confirmed_by": "C10-03",
    },
    {
        "id": "F-04",
        "title": "Schema validation precedes policy checks",
        "severity": "Low",
        "owasp": "API8:2023 Security Misconfiguration",
        "description": (
            "With no registered TrustedModelSchema, every update returns 422 before the policy "
            "pipeline runs; policy-rejection audit events are never emitted in this scenario."
        ),
        "confirmed_by": "source-analysis (C3-05..C3-09 symptom)",
    },
    {
        "id": "F-05",
        "title": "/docs, /redoc, /openapi.json accessible without auth",
        "severity": "Low",
        "owasp": "API9:2023 Improper Inventory Management",
        "description": "Full API schema accessible unauthenticated; risk in production.",
        "confirmed_by": "source-analysis",
    },
    {
        "id": "F-06",
        "title": "Forwarder deduplication is in-memory only",
        "severity": "Low",
        "owasp": "API4:2023 Unrestricted Resource Consumption",
        "description": (
            "_seen_keys set cleared on forwarder restart; replayed idempotency keys from "
            "the outbox retry queue could produce duplicate SIEM JSONL lines."
        ),
        "confirmed_by": "source-analysis",
    },
]


def _category_counts(results: list[dict]) -> list[dict]:
    """Aggregate pass/fail counts per category prefix (C1, C2, …)."""
    buckets: dict[str, dict] = {}
    for r in results:
        cat = r["id"].split("-")[0]
        if cat not in buckets:
            buckets[cat] = {"category": cat, "total": 0, "pass": 0, "fail": 0}
        buckets[cat]["total"] += 1
        if r["result"] == "PASS":
            buckets[cat]["pass"] += 1
        else:
            buckets[cat]["fail"] += 1
    return sorted(buckets.values(), key=lambda b: b["category"])


def main() -> None:
    if not RESULTS_PATH.exists():
        sys.exit(f"ERROR: {RESULTS_PATH} not found — run vapt_suite.py first")

    raw = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))

    summary = {
        "run": raw.get("run", ""),
        "timestamp": raw.get("timestamp", ""),
        "target": raw.get("target", ""),
        "summary": raw.get("summary", {}),
        "categories": _category_counts(raw.get("results", [])),
        "findings": _CURATED_FINDINGS,
        "generated_at": datetime.now(UTC).isoformat(),
    }

    SUMMARY_PATH.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Written {SUMMARY_PATH} ({SUMMARY_PATH.stat().st_size} bytes)")
    s = summary["summary"]
    print(f"  Run {summary['run']}: {s['total']} tests, {s['pass']} PASS, {s['fail']} FAIL")
    print(f"  {len(_CURATED_FINDINGS)} finding(s) included (curated F-01..F-06)")


if __name__ == "__main__":
    main()
