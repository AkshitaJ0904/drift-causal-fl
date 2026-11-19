"""Add audit_outbox table for transactional outbox pattern.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-11-06

Purpose
-------
Provides durable, at-least-once delivery of audit events to an external
destination.  Outbox records are written atomically with the business state
change that generates the audit event, so no event is lost to a process crash
between the state change and a separate delivery call.

Delivery workers claim batches using ``SELECT FOR UPDATE SKIP LOCKED``
(PostgreSQL) and mark records delivered only after successful external
delivery.  Failed or unclaimed records remain pending for retry.

Downgrade
---------
``downgrade()`` drops the table.  Any pending or undelivered outbox records
are discarded.  Run only against a non-production database or after all
pending events have been delivered.
"""

import sqlalchemy as sa

from alembic import op

# Revision identifiers used by Alembic.
revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_outbox",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column(
            "event_id",
            sa.Integer,
            sa.ForeignKey("audit_events.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("client_id", sa.String(128), nullable=True),
        sa.Column("update_id", sa.String(128), nullable=True),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("attempt_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("claimed_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_unique_constraint(
        "uq_audit_outbox_idempotency_key",
        "audit_outbox",
        ["idempotency_key"],
    )
    op.create_index("ix_audit_outbox_status", "audit_outbox", ["status"])
    op.create_index(
        "ix_audit_outbox_claimed_until", "audit_outbox", ["claimed_until"]
    )


def downgrade() -> None:
    op.drop_index("ix_audit_outbox_claimed_until", table_name="audit_outbox")
    op.drop_index("ix_audit_outbox_status", table_name="audit_outbox")
    op.drop_constraint(
        "uq_audit_outbox_idempotency_key",
        "audit_outbox",
        type_="unique",
    )
    op.drop_table("audit_outbox")
