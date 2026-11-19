"""add structured detection and audit evidence to update approvals

Revision ID: a9b11270d3c1
Revises: 312321b36f52
Create Date: 2026-11-05

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a9b11270d3c1"
down_revision: str | Sequence[str] | None = "312321b36f52"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "update_approvals",
        sa.Column("sample_count", sa.Integer(), nullable=True),
    )
    op.add_column(
        "update_approvals",
        sa.Column("risk_score", sa.Integer(), nullable=True),
    )
    op.add_column(
        "update_approvals",
        sa.Column("risk_severity", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "update_approvals",
        sa.Column("suspicious", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "update_approvals",
        sa.Column("anomaly_reasons", sa.JSON(), nullable=True),
    )
    op.add_column(
        "update_approvals",
        sa.Column(
            "detector_version",
            sa.String(length=64),
            nullable=True,
        ),
    )
    op.add_column(
        "update_approvals",
        sa.Column("detector_config", sa.JSON(), nullable=True),
    )
    op.add_column(
        "update_approvals",
        sa.Column(
            "audit_status",
            sa.String(length=16),
            nullable=True,
        ),
    )
    op.add_column(
        "update_approvals",
        sa.Column("audit_failures", sa.JSON(), nullable=True),
    )
    op.create_check_constraint(
        "ck_update_approvals_positive_sample_count",
        "update_approvals",
        "sample_count IS NULL OR sample_count > 0",
    )
    op.create_check_constraint(
        "ck_update_approvals_risk_score_range",
        "update_approvals",
        "risk_score IS NULL OR (risk_score >= 0 AND risk_score <= 100)",
    )
    op.create_check_constraint(
        "ck_update_approvals_risk_severity",
        "update_approvals",
        "risk_severity IS NULL OR risk_severity IN "
        "('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')",
    )
    op.create_check_constraint(
        "ck_update_approvals_audit_status",
        "update_approvals",
        "audit_status IS NULL OR audit_status IN ('pending', 'persisted', 'failed')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_update_approvals_audit_status",
        "update_approvals",
        type_="check",
    )
    op.drop_constraint(
        "ck_update_approvals_positive_sample_count",
        "update_approvals",
        type_="check",
    )
    op.drop_constraint(
        "ck_update_approvals_risk_severity",
        "update_approvals",
        type_="check",
    )
    op.drop_constraint(
        "ck_update_approvals_risk_score_range",
        "update_approvals",
        type_="check",
    )
    op.drop_column("update_approvals", "audit_failures")
    op.drop_column("update_approvals", "audit_status")
    op.drop_column("update_approvals", "detector_config")
    op.drop_column("update_approvals", "detector_version")
    op.drop_column("update_approvals", "anomaly_reasons")
    op.drop_column("update_approvals", "suspicious")
    op.drop_column("update_approvals", "risk_severity")
    op.drop_column("update_approvals", "risk_score")
    op.drop_column("update_approvals", "sample_count")
