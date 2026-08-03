"""Neon PostgreSQL metadata persistence."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from app.core.config import Settings
from app.core.retry import run_with_retry
from app.services.errors import DuplicateUploadError, InfrastructureError


@dataclass(frozen=True)
class UploadRecord:
    id: UUID
    original_filename: str
    object_key: str
    content_type: str
    size_bytes: int
    sha256: str
    status: str
    b2_bucket: str
    created_at: datetime


class NeonDatabase:
    """Minimal PostgreSQL repository for upload metadata."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._schema_ready = False
        self._schema_lock = threading.Lock()

    @property
    def connection_string(self) -> str:
        database_url = self._settings.database_url
        if database_url is None:
            raise InfrastructureError(
                "database_not_configured",
                "Upload metadata storage is not configured.",
            )
        return database_url.get_secret_value()

    @staticmethod
    def _is_retriable(exception: Exception) -> bool:
        return isinstance(
            exception,
            (psycopg.OperationalError, psycopg.InterfaceError),
        )

    def _run(self, operation_name: str, operation):
        try:
            return run_with_retry(
                operation,
                operation_name=operation_name,
                attempts=self._settings.infrastructure_retry_attempts,
                is_retriable=self._is_retriable,
            )
        except InfrastructureError:
            raise
        except psycopg.Error as exception:
            raise InfrastructureError(
                "database_unavailable",
                "Upload metadata storage is currently unavailable.",
            ) from exception

    def ensure_schema(self) -> None:
        if self._schema_ready:
            return

        with self._schema_lock:
            if self._schema_ready:
                return

            def create_schema() -> None:
                with psycopg.connect(
                    self.connection_string,
                    connect_timeout=10,
                ) as connection:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            """
                            CREATE TABLE IF NOT EXISTS uploads (
                                id UUID PRIMARY KEY,
                                original_filename TEXT NOT NULL,
                                object_key TEXT NOT NULL UNIQUE,
                                content_type TEXT NOT NULL,
                                size_bytes BIGINT NOT NULL CHECK (size_bytes > 0),
                                sha256 CHAR(64) NOT NULL UNIQUE,
                                status TEXT NOT NULL
                                    CHECK (status IN ('uploading', 'stored', 'failed')),
                                b2_bucket TEXT NOT NULL,
                                failure_code TEXT,
                                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                            )
                            """
                        )
                        cursor.execute(
                            """
                            CREATE INDEX IF NOT EXISTS uploads_created_at_idx
                            ON uploads (created_at DESC)
                            """
                        )

            self._run("database_schema", create_schema)
            self._schema_ready = True

    @staticmethod
    def _to_record(row: dict) -> UploadRecord:
        return UploadRecord(
            id=row["id"],
            original_filename=row["original_filename"],
            object_key=row["object_key"],
            content_type=row["content_type"],
            size_bytes=row["size_bytes"],
            sha256=row["sha256"],
            status=row["status"],
            b2_bucket=row["b2_bucket"],
            created_at=row["created_at"],
        )

    def find_by_sha256(self, sha256: str) -> UploadRecord | None:
        self.ensure_schema()

        def query() -> UploadRecord | None:
            with psycopg.connect(
                self.connection_string,
                connect_timeout=10,
                row_factory=dict_row,
            ) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT id, original_filename, object_key, content_type,
                               size_bytes, sha256, status, b2_bucket, created_at
                        FROM uploads
                        WHERE sha256 = %s
                        """,
                        (sha256,),
                    )
                    row = cursor.fetchone()
                    return self._to_record(row) if row else None

        return self._run("database_find_duplicate", query)

    def reserve(
        self,
        *,
        upload_id: UUID,
        original_filename: str,
        object_key: str,
        content_type: str,
        size_bytes: int,
        sha256: str,
        b2_bucket: str,
    ) -> UploadRecord:
        self.ensure_schema()

        def insert() -> UploadRecord:
            try:
                with psycopg.connect(
                    self.connection_string,
                    connect_timeout=10,
                    row_factory=dict_row,
                ) as connection:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            """
                            INSERT INTO uploads (
                                id, original_filename, object_key, content_type,
                                size_bytes, sha256, status, b2_bucket
                            )
                            VALUES (%s, %s, %s, %s, %s, %s, 'uploading', %s)
                            RETURNING id, original_filename, object_key, content_type,
                                      size_bytes, sha256, status, b2_bucket, created_at
                            """,
                            (
                                upload_id,
                                original_filename,
                                object_key,
                                content_type,
                                size_bytes,
                                sha256,
                                b2_bucket,
                            ),
                        )
                        row = cursor.fetchone()
                        if row is None:
                            raise InfrastructureError(
                                "database_write_failed",
                                "Upload metadata could not be saved.",
                            )
                        return self._to_record(row)
            except psycopg.errors.UniqueViolation as exception:
                existing = self.find_by_sha256(sha256)
                raise DuplicateUploadError(
                    str(existing.id) if existing else None
                ) from exception

        return self._run("database_reserve_upload", insert)

    def mark_stored(self, upload_id: UUID) -> UploadRecord:
        return self._set_status(upload_id, "stored", None)

    def mark_failed(self, upload_id: UUID, failure_code: str) -> None:
        try:
            self._set_status(upload_id, "failed", failure_code)
        except InfrastructureError:
            return

    def _set_status(
        self,
        upload_id: UUID,
        status: str,
        failure_code: str | None,
    ) -> UploadRecord:
        def update() -> UploadRecord:
            with psycopg.connect(
                self.connection_string,
                connect_timeout=10,
                row_factory=dict_row,
            ) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE uploads
                        SET status = %s, failure_code = %s, updated_at = NOW()
                        WHERE id = %s
                        RETURNING id, original_filename, object_key, content_type,
                                  size_bytes, sha256, status, b2_bucket, created_at
                        """,
                        (status, failure_code, upload_id),
                    )
                    row = cursor.fetchone()
                    if row is None:
                        raise InfrastructureError(
                            "upload_metadata_missing",
                            "Upload metadata could not be updated.",
                        )
                    return self._to_record(row)

        return self._run("database_update_upload", update)
