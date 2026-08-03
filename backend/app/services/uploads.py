"""Upload orchestration across validation, Neon, and B2."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

from app.core.config import Settings
from app.integrations.b2 import GenblazeB2Storage
from app.integrations.database import NeonDatabase, UploadRecord
from app.services.errors import DuplicateUploadError, InfrastructureError
from app.services.file_validation import ValidatedUpload


class UploadService:
    def __init__(self, settings: Settings) -> None:
        self._database = NeonDatabase(settings)
        self._storage = GenblazeB2Storage(settings)

    async def store(self, upload: ValidatedUpload) -> UploadRecord:
        existing = await asyncio.to_thread(
            self._database.find_by_sha256,
            upload.sha256,
        )
        if existing is not None:
            raise DuplicateUploadError(str(existing.id))

        upload_id = uuid4()
        date_prefix = datetime.now(UTC).strftime("%Y/%m/%d")
        object_key = (
            f"uploads/{date_prefix}/{upload_id}/"
            f"{upload.sha256[:16]}{upload.extension}"
        )
        bucket_name = self._storage.bucket_name

        await asyncio.to_thread(
            self._database.reserve,
            upload_id=upload_id,
            original_filename=upload.original_filename,
            object_key=object_key,
            content_type=upload.content_type,
            size_bytes=upload.size_bytes,
            sha256=upload.sha256,
            b2_bucket=bucket_name,
        )

        try:
            await asyncio.to_thread(
                self._storage.put,
                key=object_key,
                data=upload.data,
                content_type=upload.content_type,
                upload_id=str(upload_id),
                sha256=upload.sha256,
            )
            return await asyncio.to_thread(
                self._database.mark_stored,
                upload_id,
            )
        except InfrastructureError as exception:
            await asyncio.to_thread(
                self._database.mark_failed,
                upload_id,
                exception.code,
            )
            await asyncio.to_thread(self._storage.delete, object_key)
            raise

    def close(self) -> None:
        self._storage.close()
