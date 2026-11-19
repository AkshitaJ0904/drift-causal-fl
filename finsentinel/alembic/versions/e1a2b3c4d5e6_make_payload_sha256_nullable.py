"""Make payload_sha256 nullable and enforce hex format constraint.

Revision ID: e1a2b3c4d5e6
Revises: d5e3f7a1b8c0
Create Date: 2026-11-06

Historical payload hash problem
--------------------------------
Migration 312321b36f52 added ``payload_sha256`` as NOT NULL without a
server_default or backfill.  Migration d5e3f7a1b8c0 added a length-only
CHECK constraint but documented a DBA "sentinel" backfill procedure that was
internally inconsistent: the sentinel value ("UNKNOWN_PAYLOAD_HASH_PRE_MIGRATION
_312321b36f52", 47 chars) is shorter than 64 characters and would be rejected
by the ``length(payload_sha256) = 64`` constraint it accompanied.

More importantly, historical payload hashes CANNOT be reconstructed: the
server never stores raw payload bytes, only the SHA-256 digest submitted by the
client and re-verified during ingestion.  Backfilling with an invented hash
would fabricate integrity evidence.  Backfilling with a sentinel that is not a
valid hex digest risks propagating misleading data to consumers of the approval
record.

Correct representation of unverifiable legacy records
------------------------------------------------------
NULL is the honest representation of "this record predates payload hash
verification".  Consumers of the approval record must treat NULL as
"unverifiable", not as "valid".

This migration:
  1. Drops the length-only constraint added by d5e3f7a1b8c0.
  2. Makes ``payload_sha256`` nullable (NULL = unverifiable legacy hash).
  3. Adds a cross-dialect constraint: NULL or exactly 64 characters.
  4. On PostgreSQL, also enforces lowercase hex character set via regex.

Security consequence of NULL
-----------------------------
``is_approved()`` in enforcement/approval_service.py evaluates:
    WHERE payload_sha256 == <submitted_hash>
A NULL column value never equals a submitted hash string, so legacy records
(NULL) cannot pass the approval gate and can never be aggregated.  The
application layer also validates all new hashes via ``_SHA256_PATTERN``
before inserting, so all post-migration rows have a verified hex digest.

Downgrade note
--------------
Downgrading makes the column NOT NULL again.  Any row whose ``payload_sha256``
is NULL will cause the migration to fail on PostgreSQL.  Before downgrading,
the DBA must either delete or update all legacy NULL rows.  This data loss is
intentional: NULL rows cannot be given valid hashes post-hoc.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e1a2b3c4d5e6"
down_revision: str | Sequence[str] | None = "d5e3f7a1b8c0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Replace the length constraint added by d5e3f7a1b8c0 with the
    #    explicitly named nullable-aware form.
    op.drop_constraint(
        "ck_update_approvals_payload_sha256_length",
        "update_approvals",
        type_="check",
    )

    # 2. No-op on databases upgraded from the corrected 312321b36f52 (which
    #    already adds the column as nullable=True).  Retained as a safety net
    #    for any database that was upgraded from the original NOT NULL form.
    op.alter_column(
        "update_approvals",
        "payload_sha256",
        nullable=True,
        existing_type=sa.String(64),
    )

    # 3. Cross-dialect constraint: NULL (legacy) or exactly 64 characters.
    op.create_check_constraint(
        "ck_update_approvals_payload_sha256_format",
        "update_approvals",
        "payload_sha256 IS NULL OR length(payload_sha256) = 64",
    )

    # 4. PostgreSQL: additionally enforce lowercase hex character set.
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.execute(sa.text(
            "ALTER TABLE update_approvals "
            "ADD CONSTRAINT ck_update_approvals_payload_sha256_hex "
            "CHECK (payload_sha256 IS NULL OR payload_sha256 ~ '^[0-9a-f]{64}$')"
        ))


def downgrade() -> None:
    # Remove the PostgreSQL hex-character constraint first.
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.execute(sa.text(
            "ALTER TABLE update_approvals "
            "DROP CONSTRAINT IF EXISTS ck_update_approvals_payload_sha256_hex"
        ))

    op.drop_constraint(
        "ck_update_approvals_payload_sha256_format",
        "update_approvals",
        type_="check",
    )

    # Reverting to NOT NULL will fail if any row has payload_sha256 IS NULL.
    # The DBA must resolve all NULL rows before downgrading.
    op.alter_column(
        "update_approvals",
        "payload_sha256",
        nullable=False,
        existing_type=sa.String(64),
    )

    op.create_check_constraint(
        "ck_update_approvals_payload_sha256_length",
        "update_approvals",
        "length(payload_sha256) = 64",
    )
