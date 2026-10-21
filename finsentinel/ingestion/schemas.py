
"""Validated metadata contracts for incoming federated-learning updates."""

from datetime import datetime, timezone
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator


Identifier = Annotated[
    str,
    Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$"),
]


class UpdateEnvelope(BaseModel):
    """Metadata describing an update; this does not verify its authenticity."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    update_id: Identifier
    client_id: Identifier
    model_version: Identifier

    round_number: int = Field(ge=1)
    payload_sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    payload_size_bytes: int = Field(gt=0, le=500_000_000)

    created_at: datetime
    signature: str = Field(min_length=1, max_length=4096)
    signing_key_id: Identifier

    @field_validator("created_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must include a timezone")
        return value.astimezone(timezone.utc)
