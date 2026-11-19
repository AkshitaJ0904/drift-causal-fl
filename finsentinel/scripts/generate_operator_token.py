"""Generate a cryptographically secure operator token for FinSentinel.

Usage:
    python scripts/generate_operator_token.py

Prints a single hex-encoded token to stdout.  The token is 32 random bytes
(256 bits), encoded as 64 lowercase hex characters.  This meets and exceeds
the minimum length required by FINSENTINEL_OPERATOR_TOKEN.

Set the token in the environment before starting the service:

    Windows (PowerShell):
        $env:FINSENTINEL_OPERATOR_TOKEN = (python scripts/generate_operator_token.py)

    Linux / macOS:
        export FINSENTINEL_OPERATOR_TOKEN=$(python scripts/generate_operator_token.py)

Or add it to the .env file (never commit .env to version control):
    FINSENTINEL_OPERATOR_TOKEN=<paste token here>

ROTATION PROCEDURE
------------------
1. Generate a new token:
       python scripts/generate_operator_token.py
2. Update FINSENTINEL_OPERATOR_TOKEN in the .env file or environment.
3. Restart the service (NSSM: `nssm restart finsentinel`).
4. Distribute the new token to authorized operators.
5. Invalidate any sessions using the old token.

The old token is immediately invalid once the service restarts with the new one.
"""

import secrets


def main() -> None:
    token = secrets.token_hex(32)  # 32 bytes = 64 hex chars = 256 bits
    print(token)


if __name__ == "__main__":
    main()
