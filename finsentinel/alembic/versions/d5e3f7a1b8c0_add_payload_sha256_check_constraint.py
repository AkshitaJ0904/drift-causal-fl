"""Add missing payload_sha256 length check constraint to update_approvals.

Revision ID: d5e3f7a1b8c0
Revises: c4f2a8b1e930
Create Date: 2026-11-06

SUPERSEDED NOTE (2026-11-06)
----------------------------
Migration e1a2b3c4d5e6 (which follows this one in the chain) replaces the
length-only strategy here with a correct nullable strategy.  The DBA procedure
described in earlier drafts of this file was internally inconsistent: the
sentinel value "UNKNOWN_PAYLOAD_HASH_PRE_MIGRATION_312321b36f52" is 47
characters, which is shorter than 64, and would have been REJECTED by the
``length(payload_sha256) = 64`` constraint this migration adds.

Additionally, historical SHA-256 digests cannot be reconstructed because the
server never stores raw payload bytes.  Using any placeholder hash would
fabricate integrity evidence.

The correct approach (implemented in e1a2b3c4d5e6) is to make the column
nullable so that legacy records carry NULL rather than a fabricated sentinel.

Background
----------
Migration 312321b36f52 added ``payload_sha256`` as NOT NULL with no
server_default and no backfill.  On a PostgreSQL database that already
contains rows in ``update_approvals``, that migration fails with:

    ProgrammingError: column "payload_sha256" of relation "update_approvals"
    contains null values

This migration adds only the ORM ``length = 64`` constraint that was declared
in the model but absent from the migration chain.  The full fix for the
nullable strategy is in e1a2b3c4d5e6 (which immediately follows this migration).

Downgrade note
--------------
Dropping this check constraint is safe and reversible; no data is lost.
"""
from collections.abc import Sequence

from alembic import op

revision: str = "d5e3f7a1b8c0"
down_revision: str | Sequence[str] | None = "c4f2a8b1e930"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # payload_sha256 is nullable since migration 312321b36f52 (which was
    # corrected to add the column as nullable=True).  SQL three-valued logic
    # means CHECK (length(payload_sha256) = 64) already accepts NULL rows
    # (NULL is not FALSE), but we use the explicit nullable-aware form here for
    # clarity and to match the ORM model declaration.
    # On SQLite, ALTER TABLE ADD CONSTRAINT is not supported; the ORM-level
    # constraint handles SQLite in-process validation.
    op.create_check_constraint(
        "ck_update_approvals_payload_sha256_length",
        "update_approvals",
        "payload_sha256 IS NULL OR length(payload_sha256) = 64",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_update_approvals_payload_sha256_length",
        "update_approvals",
        type_="check",
    )
