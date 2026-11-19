"""Add sample_count_provenance column to update_approvals.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-11-06

Records whether the sample count for an ingested update was independently
verified by a trusted provider or is client-claimed only.  Existing rows
receive the default value "client_claimed" (conservative: no retroactive
trust upgrade).
"""

import sqlalchemy as sa

from alembic import op

revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("update_approvals") as batch_op:
        batch_op.add_column(
            sa.Column(
                "sample_count_provenance",
                sa.String(32),
                nullable=True,
                server_default="client_claimed",
            )
        )
        batch_op.create_check_constraint(
            "ck_update_approvals_sample_count_provenance",
            "sample_count_provenance IS NULL OR sample_count_provenance IN "
            "('client_claimed', 'provider_verified')",
        )


def downgrade() -> None:
    with op.batch_alter_table("update_approvals") as batch_op:
        batch_op.drop_constraint(
            "ck_update_approvals_sample_count_provenance",
            type_="check",
        )
        batch_op.drop_column("sample_count_provenance")
