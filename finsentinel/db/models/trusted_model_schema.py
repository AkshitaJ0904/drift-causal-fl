
"""ORM model for the durable trusted model schema registry."""

from datetime import datetime

from sqlalchemy import JSON, DateTime, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from core.supabase.base import Base


class TrustedModelSchema(Base):
    """Persist model tensor specifications across process restarts and workers."""

    __tablename__ = "trusted_model_schemas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    model_version: Mapped[str] = mapped_column(String(128), nullable=False)
    tensor_specs: Mapped[dict] = mapped_column(JSON, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint("model_version", name="uq_trusted_model_schemas_version"),
        Index("ix_trusted_model_schemas_version", "model_version"),
    )
