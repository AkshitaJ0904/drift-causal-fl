"""Add replay_records table for durable replay protection.

Revision ID: c4f2a8b1e930
Revises: a9b11270d3c1
Create Date: 2026-11-06

Purpose
-------
Adds a durable, database-backed replay-protection store so that update IDs
are blocked across process restarts and worker processes, not only within a
single in-memory registry.

The unique constraint on (client_id, update_id) is the authoritative replay
gate.  The in-memory lock in core.replay_protection remains for intra-process
thread safety and fast-path duplicate detection.

Safety notes
------------
* This migration only creates a new table; no existing columns are modified.
* Downgrade drops the table and permanently loses all reservation records.
  Do not downgrade a production deployment without first verifying that the
  loss of durable replay state is acceptable.
"""

import sqlalchemy as sa

from alembic import op

revision = "c4f2a8b1e930"
down_revision = "a9b11270d3c1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "replay_records",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("client_id", sa.String(128), nullable=False),
        sa.Column("update_id", sa.String(128), nullable=False),
        sa.Column("payload_fingerprint", sa.String(64), nullable=False),
        sa.Column("finalized", sa.Boolean, nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("client_id", "update_id", name="uq_replay_client_update"),
    )
    op.create_index(
        "ix_replay_records_client_id",
        "replay_records",
        ["client_id"],
    )
    op.create_index(
        "ix_replay_records_update_id",
        "replay_records",
        ["update_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_replay_records_update_id", table_name="replay_records")
    op.drop_index("ix_replay_records_client_id", table_name="replay_records")
    op.drop_table("replay_records")
