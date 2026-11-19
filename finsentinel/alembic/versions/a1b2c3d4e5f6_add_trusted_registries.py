"""Add durable trusted-key and trusted-model-schema registry tables.

Revision ID: a1b2c3d4e5f6
Revises: e1a2b3c4d5e6
Create Date: 2026-11-06

Purpose
-------
Replaces the process-local in-memory key registry (core/key_registry.py) and
model-schema registry (core/model_registry.py) with durable DB-backed stores.

trusted_keys
  Persists Ed25519 public keys (PEM), the client identity they are bound to,
  an optional per-key sample-count ceiling, and an is_active / revoked_at
  pair for explicit revocation without row deletion.

trusted_model_schemas
  Persists tensor-spec dictionaries for each named model version.  The JSON
  column stores {tensor_name: [[dim, ...], "dtype"]} where shape dimensions
  are serialized as JSON arrays.

Security notes
--------------
* Revoked keys (is_active = FALSE) are never returned by get_trusted_key();
  there is no in-memory cache that could serve a stale revoked key.
* DB failures on security-critical reads raise RegistryUnavailableError
  (fail-closed), not return None (which looks like "key not found").
* The unique constraint on key_id prevents duplicate registration races.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "e1a2b3c4d5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "trusted_keys",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("key_id", sa.String(128), nullable=False),
        sa.Column("client_id", sa.String(128), nullable=False),
        sa.Column("public_key_pem", sa.Text, nullable=False),
        sa.Column("max_sample_count", sa.Integer, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("key_id", name="uq_trusted_keys_key_id"),
    )
    op.create_index("ix_trusted_keys_client_id", "trusted_keys", ["client_id"])
    op.create_index("ix_trusted_keys_is_active", "trusted_keys", ["is_active"])

    op.create_table(
        "trusted_model_schemas",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("model_version", sa.String(128), nullable=False),
        sa.Column("tensor_specs", sa.JSON, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("model_version", name="uq_trusted_model_schemas_version"),
    )
    op.create_index(
        "ix_trusted_model_schemas_version", "trusted_model_schemas", ["model_version"]
    )


def downgrade() -> None:
    op.drop_index("ix_trusted_model_schemas_version", table_name="trusted_model_schemas")
    op.drop_table("trusted_model_schemas")
    op.drop_index("ix_trusted_keys_is_active", table_name="trusted_keys")
    op.drop_index("ix_trusted_keys_client_id", table_name="trusted_keys")
    op.drop_table("trusted_keys")
