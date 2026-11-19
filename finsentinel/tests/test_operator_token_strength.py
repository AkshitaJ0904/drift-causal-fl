"""Tests for operator token minimum-strength validation.

Coverage:
- check_operator_token_strength() logs ERROR when token is too short.
- check_operator_token_strength() is silent when token meets minimum length.
- check_operator_token_strength() is silent when token is absent.
- generate_operator_token.py produces a token of sufficient length.
- generate_operator_token.py output is valid hex.
- Each call produces a unique token (randomness).
"""
from __future__ import annotations

import os
import subprocess
import sys
from unittest.mock import patch


def test_strength_check_silent_when_token_absent():
    """No log entry when FINSENTINEL_OPERATOR_TOKEN is unset."""
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("FINSENTINEL_OPERATOR_TOKEN", None)
        from api._auth import check_operator_token_strength
        with patch("api._auth.logger") as mock_log:
            check_operator_token_strength()
        mock_log.error.assert_not_called()


def test_strength_check_silent_when_token_strong():
    """No log entry when token is 32+ characters."""
    strong_token = "a" * 64  # 64 chars, well above minimum
    with patch.dict(os.environ, {"FINSENTINEL_OPERATOR_TOKEN": strong_token}):
        from api._auth import check_operator_token_strength
        with patch("api._auth.logger") as mock_log:
            check_operator_token_strength()
        mock_log.error.assert_not_called()


def test_strength_check_exactly_at_minimum_is_acceptable():
    """Token of exactly _MIN_TOKEN_BYTES chars generates no error."""
    from api._auth import _MIN_TOKEN_BYTES, check_operator_token_strength
    token_at_min = "b" * _MIN_TOKEN_BYTES
    with patch.dict(os.environ, {"FINSENTINEL_OPERATOR_TOKEN": token_at_min}):
        with patch("api._auth.logger") as mock_log:
            check_operator_token_strength()
        mock_log.error.assert_not_called()


def test_strength_check_logs_error_when_token_too_short():
    """ERROR is logged when token is shorter than _MIN_TOKEN_BYTES."""
    from api._auth import _MIN_TOKEN_BYTES, check_operator_token_strength
    short_token = "x" * (_MIN_TOKEN_BYTES - 1)
    with patch.dict(os.environ, {"FINSENTINEL_OPERATOR_TOKEN": short_token}):
        with patch("api._auth.logger") as mock_log:
            check_operator_token_strength()
        mock_log.error.assert_called_once()
        call_args = mock_log.error.call_args[0][0]
        assert "too short" in call_args.lower() or "minimum" in call_args.lower()


def test_strength_check_error_contains_actual_length():
    """The error message includes the actual token length."""
    from api._auth import check_operator_token_strength
    short_token = "y" * 10
    with patch.dict(os.environ, {"FINSENTINEL_OPERATOR_TOKEN": short_token}):
        with patch("api._auth.logger") as mock_log:
            check_operator_token_strength()
        args = mock_log.error.call_args
        # The format string uses %d placeholders; args[1] is the first substitution value.
        format_args = args[0][1:]  # (format_string, arg1, arg2, ...)
        assert 10 in format_args, f"Expected 10 in format args; got {format_args}"


def test_generate_operator_token_sufficient_length():
    """generate_operator_token.py produces a token >= 32 characters."""
    result = subprocess.run(
        [sys.executable, "scripts/generate_operator_token.py"],
        capture_output=True,
        text=True,
        cwd="D:\\prj 4\\drift-causal-fl\\finsentinel",
    )
    assert result.returncode == 0
    token = result.stdout.strip()
    assert len(token) >= 32, f"Token too short: {len(token)} chars"


def test_generate_operator_token_is_valid_hex():
    """generate_operator_token.py output is lowercase hex."""
    result = subprocess.run(
        [sys.executable, "scripts/generate_operator_token.py"],
        capture_output=True,
        text=True,
        cwd="D:\\prj 4\\drift-causal-fl\\finsentinel",
    )
    token = result.stdout.strip()
    int(token, 16)  # Raises ValueError if not valid hex


def test_generate_operator_token_produces_64_hex_chars():
    """Token is exactly 64 hex characters (32 bytes = 256 bits)."""
    result = subprocess.run(
        [sys.executable, "scripts/generate_operator_token.py"],
        capture_output=True,
        text=True,
        cwd="D:\\prj 4\\drift-causal-fl\\finsentinel",
    )
    token = result.stdout.strip()
    assert len(token) == 64, f"Expected 64 hex chars, got {len(token)}"


def test_generate_operator_token_uniqueness():
    """Two consecutive calls produce different tokens."""
    tokens = set()
    for _ in range(3):
        result = subprocess.run(
            [sys.executable, "scripts/generate_operator_token.py"],
            capture_output=True,
            text=True,
            cwd="D:\\prj 4\\drift-causal-fl\\finsentinel",
        )
        tokens.add(result.stdout.strip())
    assert len(tokens) == 3, "Token generator produced duplicates"
