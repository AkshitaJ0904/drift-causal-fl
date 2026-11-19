"""Risk-based initial review actions for detected updates."""

from typing import Literal

ApprovalAction = Literal["pending_approval", "quarantined"]


def select_initial_approval_status(
    severity: str,
    *,
    high_risk_action: ApprovalAction = "quarantined",
) -> ApprovalAction:
    """Keep low and medium risk pending; quarantine high and critical by default.

    This policy never approves an update. A high anomaly score is a review
    signal and does not establish malicious intent.
    """
    if severity not in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}:
        raise ValueError("Unknown detection severity.")

    if high_risk_action not in {"pending_approval", "quarantined"}:
        raise ValueError("high_risk_action must be pending_approval or quarantined.")

    if severity in {"HIGH", "CRITICAL"}:
        return high_risk_action

    return "pending_approval"
