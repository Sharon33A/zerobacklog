"""Upload orchestration across validation, Neon, and B2."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.core.config import Settings
from app.integrations.b2 import GenblazeB2Storage
from app.integrations.database import NeonDatabase, UploadRecord
from app.services.errors import InfrastructureError
from app.services.file_validation import ValidatedUpload


class UploadService:
    def __init__(self, settings: Settings) -> None:
        self._database = NeonDatabase(settings)
        self._storage = GenblazeB2Storage(settings)

    async def store(
        self,
        upload: ValidatedUpload,
        *,
        project_id: UUID,
    ) -> UploadRecord:
        existing = await asyncio.to_thread(
            self._database.find_by_sha256,
            upload.sha256,
            project_id,
        )

        upload_id = uuid4()
        if existing is None:
            date_prefix = datetime.now(UTC).strftime("%Y/%m/%d")
            object_key = (
                f"uploads/{date_prefix}/{upload_id}/"
                f"{upload.sha256[:16]}{upload.extension}"
            )
        else:
            object_key = existing.object_key
        bucket_name = self._storage.bucket_name

        await asyncio.to_thread(
            self._database.reserve,
            upload_id=upload_id,
            project_id=project_id,
            original_filename=upload.original_filename,
            object_key=object_key,
            content_type=upload.content_type,
            size_bytes=upload.size_bytes,
            sha256=upload.sha256,
            b2_bucket=bucket_name,
        )

        try:
            if existing is not None:
                record = await asyncio.to_thread(
                    self._database.mark_stored,
                    upload_id,
                )
                await asyncio.to_thread(
                    self._database.initialize_resource,
                    upload_id,
                    project_id,
                )
                return record

            await asyncio.to_thread(
                self._storage.put,
                key=object_key,
                data=upload.data,
                content_type=upload.content_type,
                upload_id=str(upload_id),
                sha256=upload.sha256,
            )
            record = await asyncio.to_thread(
                self._database.mark_stored,
                upload_id,
            )
            await asyncio.to_thread(
                self._database.initialize_resource,
                upload_id,
                project_id,
            )
            return record
        except InfrastructureError as exception:
            await asyncio.to_thread(
                self._database.mark_failed,
                upload_id,
                exception.code,
            )
            if existing is None:
                await asyncio.to_thread(self._storage.delete, object_key)
            raise

    def close(self) -> None:
        self._storage.close()
