
"""Shared operator bearer-token authentication for FinSentinel APIs."""

import hmac
import logging
import os

from fastapi import HTTPException, Request

logger = logging.getLogger(__name__)

_OPERATOR_TOKEN_ENV = "FINSENTINEL_OPERATOR_TOKEN"
_MAX_ID_LENGTH = 128
_MIN_TOKEN_BYTES = 32  # 256-bit minimum; generated tokens are 32 random bytes → 64 hex chars


def check_operator_token_strength() -> None:
    """Log a warning when the operator token is configured but too weak.

    Called at application startup.  Returns silently when the token is absent
    (the separate S0-1 absence check handles that case) or meets the minimum
    length requirement.  Logs an ERROR when the token is present but shorter
    than ``_MIN_TOKEN_BYTES`` characters — a short token is guessable and must
    not be used in production.
    """
    token = os.getenv(_OPERATOR_TOKEN_ENV, "").strip()
    if not token:
        return  # Absence is handled by the S0-1 startup warning.
    if len(token) < _MIN_TOKEN_BYTES:
        logger.error(
            "FINSENTINEL_OPERATOR_TOKEN is configured but too short "
            "(%d characters; minimum %d). "
            "A short token is vulnerable to brute-force guessing. "
            "Generate a strong token with: "
            "python scripts/generate_operator_token.py",
            len(token),
            _MIN_TOKEN_BYTES,
        )


def require_operator_auth(request: Request) -> None:
    """Validate the operator bearer token; raise 401/503 on failure."""
    configured_token = os.getenv(_OPERATOR_TOKEN_ENV, "").strip()
    if not configured_token:
        raise HTTPException(
            status_code=503,
            detail="Operator authentication is not configured.",
        )
    auth_header = request.headers.get("authorization", "")
    if not auth_header.lower().startswith("bearer "):
        raise HTTPException(
            status_code=401,
            detail="Operator authentication required.",
        )
    provided_token = auth_header[7:].strip()
    if not hmac.compare_digest(configured_token, provided_token):
        raise HTTPException(
            status_code=401,
            detail="Invalid operator token.",
        )


def validate_path_id(value: str, name: str) -> None:
    """Reject path parameters that exceed the maximum length or contain control characters.

    Both limits mirror the String(128) DB column constraints, surfacing the
    error at the HTTP layer with a 422 instead of an unhandled DB exception.
    """
    if len(value) > _MAX_ID_LENGTH:
        raise HTTPException(
            status_code=422,
            detail=f"{name} must not exceed {_MAX_ID_LENGTH} characters.",
        )
    if any(ord(c) < 0x20 for c in value):
        raise HTTPException(
            status_code=422,
            detail=f"{name} must not contain control characters.",
        )
