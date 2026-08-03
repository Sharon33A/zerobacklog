"""Upload API response contracts."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.integrations.database import UploadRecord


class UploadMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    filename: str
    content_type: str
    size_bytes: int
    sha256: str
    status: Literal["stored"]
    bucket: str
    object_key: str
    created_at: datetime

    @classmethod
    def from_record(cls, record: UploadRecord) -> "UploadMetadata":
        return cls(
            id=record.id,
            filename=record.original_filename,
            content_type=record.content_type,
            size_bytes=record.size_bytes,
            sha256=record.sha256,
            status="stored",
            bucket=record.b2_bucket,
            object_key=record.object_key,
            created_at=record.created_at,
        )


class UploadResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    upload: UploadMetadata
