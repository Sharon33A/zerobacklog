"""Backblaze B2 storage through the official Genblaze SDK."""

from __future__ import annotations

import threading
from dataclasses import dataclass

from genblaze_core import StorageError
from genblaze_s3 import S3StorageBackend

from app.core.config import Settings
from app.core.retry import run_with_retry
from app.services.errors import InfrastructureError


@dataclass(frozen=True)
class StoredObject:
    key: str
    size_bytes: int
    durable_url: str


class GenblazeB2Storage:
    """Lazy Genblaze B2 client used for validated source uploads."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._backend: S3StorageBackend | None = None
        self._lock = threading.Lock()

    @property
    def bucket_name(self) -> str:
        bucket = (self._settings.b2_bucket_name or "").strip()
        if not bucket:
            raise InfrastructureError(
                "storage_not_configured",
                "Upload storage is not configured.",
            )
        return bucket

    def _get_backend(self) -> S3StorageBackend:
        if self._backend is not None:
            return self._backend

        with self._lock:
            if self._backend is not None:
                return self._backend

            key_id = self._settings.b2_application_key_id
            app_key = self._settings.b2_application_key
            region = (self._settings.b2_region or "").strip() or None
            if key_id is None or app_key is None:
                raise InfrastructureError(
                    "storage_not_configured",
                    "Upload storage is not configured.",
                )

            try:
                self._backend = S3StorageBackend.for_backblaze(
                    self.bucket_name,
                    region=region,
                    key_id=key_id.get_secret_value(),
                    app_key=app_key.get_secret_value(),
                    auto_lifecycle=False,
                    preflight=True,
                )
            except (StorageError, ValueError) as exception:
                raise InfrastructureError(
                    "storage_unavailable",
                    "Upload storage is currently unavailable.",
                ) from exception

        return self._backend

    def put(
        self,
        *,
        key: str,
        data: bytes,
        content_type: str,
        upload_id: str,
        sha256: str,
    ) -> StoredObject:
        def operation() -> StoredObject:
            backend = self._get_backend()
            backend.put(
                key,
                data,
                content_type=content_type,
                metadata={
                    "upload-id": upload_id,
                    "sha256": sha256,
                },
            )
            metadata = backend.head(key)
            if metadata is None or metadata.size != len(data):
                raise InfrastructureError(
                    "storage_verification_failed",
                    "The uploaded object could not be verified.",
                )
            return StoredObject(
                key=key,
                size_bytes=metadata.size,
                durable_url=backend.get_durable_url(key),
            )

        try:
            return run_with_retry(
                operation,
                operation_name="b2_put",
                attempts=self._settings.infrastructure_retry_attempts,
                is_retriable=lambda error: isinstance(error, StorageError)
                and error.is_retriable,
            )
        except InfrastructureError:
            raise
        except StorageError as exception:
            raise InfrastructureError(
                "storage_upload_failed",
                "The file could not be stored. Please retry.",
            ) from exception

    def get(self, key: str) -> bytes:
        """Retrieve an object with the same bounded retry policy as uploads."""

        try:
            return run_with_retry(
                lambda: self._get_backend().get(key),
                operation_name="b2_get",
                attempts=self._settings.infrastructure_retry_attempts,
                is_retriable=lambda error: isinstance(error, StorageError)
                and error.is_retriable,
            )
        except StorageError as exception:
            raise InfrastructureError(
                "storage_read_failed",
                "The stored resource could not be read. Please retry.",
            ) from exception

    def delete(self, key: str) -> None:
        try:
            self._get_backend().delete(key)
        except Exception:
            # Compensating cleanup is best effort; the original error is primary.
            return

    def close(self) -> None:
        if self._backend is not None:
            self._backend.close()
