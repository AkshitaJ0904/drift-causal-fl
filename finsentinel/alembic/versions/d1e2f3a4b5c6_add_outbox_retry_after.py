"""Add retry_after column to audit_outbox for exponential backoff.

Adds:
- ``audit_outbox.retry_after``  — nullable UTC timestamp; when non-NULL the
  outbox worker must not re-claim the record until this time passes.
  NULL means the record is immediately claimable (all existing rows and
  new records with no failed delivery).

The ``dead_letter`` status value (string) is handled entirely in application
code; no schema constraint is added here so that the status enum can evolve
without migrations.

Revision ID: d1e2f3a4b5c6
Revises:     c3d4e5f6a7b8
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "d1e2f3a4b5c6"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "audit_outbox",
        sa.Column(
            "retry_after",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_audit_outbox_retry_after",
        "audit_outbox",
        ["retry_after"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_audit_outbox_retry_after", table_name="audit_outbox")
    op.drop_column("audit_outbox", "retry_after")
