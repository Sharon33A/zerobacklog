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
from app.services.errors import InfrastructureError, ResourceNotFoundError


@dataclass(frozen=True)
class UploadRecord:
    id: UUID
    project_id: UUID
    original_filename: str
    object_key: str
    content_type: str
    size_bytes: int
    sha256: str
    status: str
    b2_bucket: str
    created_at: datetime


@dataclass(frozen=True)
class ResourceRecord:
    id: UUID
    project_id: UUID
    filename: str
    content_type: str
    size_bytes: int
    sha256: str
    source_object_key: str
    lifecycle_state: str
    readiness_status: str | None
    explanation: str | None
    technical_reason: str | None
    confidence: float | None
    extracted_character_count: int
    extracted_page_count: int | None
    total_page_count: int | None
    detected_language: str | None
    duplicate_match_id: UUID | None
    duplicate_match_filename: str | None
    duplicate_kind: str | None
    duplicate_similarity: float | None
    suggested_action: str | None
    content_summary: str | None
    extracted_object_key: str | None
    metadata_object_key: str | None
    similarity_signature: tuple[str, ...]
    approved: bool
    replacement_requested: bool
    removed: bool
    created_at: datetime
    updated_at: datetime


RESOURCE_SELECT = """
    SELECT
        u.id,
        u.project_id,
        u.original_filename AS filename,
        u.content_type,
        u.size_bytes,
        u.sha256,
        u.object_key AS source_object_key,
        r.lifecycle_state,
        r.readiness_status,
        r.explanation,
        r.technical_reason,
        r.confidence,
        r.extracted_character_count,
        r.extracted_page_count,
        r.total_page_count,
        r.detected_language,
        r.duplicate_match_id,
        duplicate.original_filename AS duplicate_match_filename,
        r.duplicate_kind,
        r.duplicate_similarity,
        r.suggested_action,
        r.content_summary,
        r.extracted_object_key,
        r.metadata_object_key,
        r.similarity_signature,
        r.approved,
        r.replacement_requested,
        r.removed_at,
        r.created_at,
        r.updated_at
    FROM uploads u
    JOIN resource_readiness r ON r.upload_id = u.id
    LEFT JOIN uploads duplicate ON duplicate.id = r.duplicate_match_id
"""


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
                                project_id UUID NOT NULL,
                                original_filename TEXT NOT NULL,
                                object_key TEXT NOT NULL,
                                content_type TEXT NOT NULL,
                                size_bytes BIGINT NOT NULL CHECK (size_bytes > 0),
                                sha256 CHAR(64) NOT NULL,
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
                            "ALTER TABLE uploads ADD COLUMN IF NOT EXISTS project_id UUID"
                        )
                        cursor.execute(
                            "UPDATE uploads SET project_id = id WHERE project_id IS NULL"
                        )
                        cursor.execute(
                            "ALTER TABLE uploads ALTER COLUMN project_id SET NOT NULL"
                        )
                        cursor.execute(
                            """
                            ALTER TABLE uploads
                            DROP CONSTRAINT IF EXISTS uploads_object_key_key
                            """
                        )
                        cursor.execute(
                            """
                            ALTER TABLE uploads
                            DROP CONSTRAINT IF EXISTS uploads_sha256_key
                            """
                        )
                        cursor.execute(
                            """
                            CREATE INDEX IF NOT EXISTS uploads_created_at_idx
                            ON uploads (created_at DESC)
                            """
                        )
                        cursor.execute(
                            """
                            CREATE INDEX IF NOT EXISTS uploads_project_sha_idx
                            ON uploads (project_id, sha256, created_at)
                            """
                        )
                        cursor.execute(
                            """
                            CREATE TABLE IF NOT EXISTS resource_readiness (
                                upload_id UUID PRIMARY KEY
                                    REFERENCES uploads(id) ON DELETE CASCADE,
                                project_id UUID NOT NULL,
                                lifecycle_state TEXT NOT NULL DEFAULT 'uploaded',
                                readiness_status TEXT CHECK (
                                    readiness_status IS NULL OR readiness_status IN (
                                        'ready', 'partial', 'low_confidence',
                                        'irrelevant', 'duplicate', 'unreadable',
                                        'unsupported', 'failed'
                                    )
                                ),
                                explanation TEXT,
                                technical_reason TEXT,
                                confidence DOUBLE PRECISION CHECK (
                                    confidence IS NULL OR
                                    (confidence >= 0 AND confidence <= 1)
                                ),
                                extracted_character_count INTEGER NOT NULL DEFAULT 0,
                                extracted_page_count INTEGER,
                                total_page_count INTEGER,
                                detected_language TEXT,
                                duplicate_match_id UUID REFERENCES uploads(id),
                                duplicate_kind TEXT CHECK (
                                    duplicate_kind IS NULL OR
                                    duplicate_kind IN ('exact', 'near')
                                ),
                                duplicate_similarity DOUBLE PRECISION,
                                suggested_action TEXT,
                                content_summary TEXT,
                                extracted_object_key TEXT,
                                metadata_object_key TEXT,
                                similarity_signature TEXT[] NOT NULL DEFAULT '{}',
                                approved BOOLEAN NOT NULL DEFAULT FALSE,
                                replacement_requested BOOLEAN NOT NULL DEFAULT FALSE,
                                removed_at TIMESTAMPTZ,
                                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                            )
                            """
                        )
                        cursor.execute(
                            """
                            CREATE INDEX IF NOT EXISTS readiness_project_idx
                            ON resource_readiness (project_id, created_at)
                            """
                        )
                        cursor.execute(
                            """
                            CREATE TABLE IF NOT EXISTS resource_state_events (
                                id BIGSERIAL PRIMARY KEY,
                                upload_id UUID NOT NULL
                                    REFERENCES uploads(id) ON DELETE CASCADE,
                                state TEXT NOT NULL,
                                occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                            )
                            """
                        )

            self._run("database_schema", create_schema)
            self._schema_ready = True

    @staticmethod
    def _to_record(row: dict) -> UploadRecord:
        return UploadRecord(
            id=row["id"],
            project_id=row["project_id"],
            original_filename=row["original_filename"],
            object_key=row["object_key"],
            content_type=row["content_type"],
            size_bytes=row["size_bytes"],
            sha256=row["sha256"],
            status=row["status"],
            b2_bucket=row["b2_bucket"],
            created_at=row["created_at"],
        )

    @staticmethod
    def _to_resource_record(row: dict) -> ResourceRecord:
        return ResourceRecord(
            id=row["id"],
            project_id=row["project_id"],
            filename=row["filename"],
            content_type=row["content_type"],
            size_bytes=row["size_bytes"],
            sha256=row["sha256"],
            source_object_key=row["source_object_key"],
            lifecycle_state=row["lifecycle_state"],
            readiness_status=row["readiness_status"],
            explanation=row["explanation"],
            technical_reason=row["technical_reason"],
            confidence=row["confidence"],
            extracted_character_count=row["extracted_character_count"],
            extracted_page_count=row["extracted_page_count"],
            total_page_count=row["total_page_count"],
            detected_language=row["detected_language"],
            duplicate_match_id=row["duplicate_match_id"],
            duplicate_match_filename=row["duplicate_match_filename"],
            duplicate_kind=row["duplicate_kind"],
            duplicate_similarity=row["duplicate_similarity"],
            suggested_action=row["suggested_action"],
            content_summary=row["content_summary"],
            extracted_object_key=row["extracted_object_key"],
            metadata_object_key=row["metadata_object_key"],
            similarity_signature=tuple(row["similarity_signature"] or ()),
            approved=row["approved"],
            replacement_requested=row["replacement_requested"],
            removed=row["removed_at"] is not None,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def find_by_sha256(
        self,
        sha256: str,
        project_id: UUID | None = None,
        exclude_upload_id: UUID | None = None,
    ) -> UploadRecord | None:
        self.ensure_schema()

        def query() -> UploadRecord | None:
            with psycopg.connect(
                self.connection_string,
                connect_timeout=10,
                row_factory=dict_row,
            ) as connection:
                with connection.cursor() as cursor:
                    conditions = ["sha256 = %s", "status = 'stored'"]
                    parameters: list[object] = [sha256]
                    if project_id is not None:
                        conditions.append("project_id = %s")
                        parameters.append(project_id)
                    if exclude_upload_id is not None:
                        conditions.append("id <> %s")
                        parameters.append(exclude_upload_id)
                    cursor.execute(
                        f"""
                        SELECT id, project_id, original_filename, object_key,
                               content_type, size_bytes, sha256, status,
                               b2_bucket, created_at
                        FROM uploads
                        WHERE {' AND '.join(conditions)}
                        ORDER BY created_at ASC
                        LIMIT 1
                        """,
                        parameters,
                    )
                    row = cursor.fetchone()
                    return self._to_record(row) if row else None

        return self._run("database_find_duplicate", query)

    def reserve(
        self,
        *,
        upload_id: UUID,
        project_id: UUID,
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
                                id, project_id, original_filename, object_key, content_type,
                                size_bytes, sha256, status, b2_bucket
                            )
                            VALUES (%s, %s, %s, %s, %s, %s, %s, 'uploading', %s)
                            RETURNING id, project_id, original_filename, object_key, content_type,
                                      size_bytes, sha256, status, b2_bucket, created_at
                            """,
                            (
                                upload_id,
                                project_id,
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
                raise InfrastructureError(
                    "database_write_conflict",
                    "Upload metadata could not be reserved.",
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
                                  size_bytes, sha256, status, b2_bucket, created_at,
                                  project_id
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

    def initialize_resource(self, upload_id: UUID, project_id: UUID) -> None:
        """Create the logical resource and its first lifecycle event."""
        self.ensure_schema()

        def insert() -> None:
            with psycopg.connect(
                self.connection_string,
                connect_timeout=10,
            ) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO resource_readiness (
                            upload_id, project_id, lifecycle_state
                        )
                        VALUES (%s, %s, 'uploaded')
                        ON CONFLICT (upload_id) DO NOTHING
                        """,
                        (upload_id, project_id),
                    )
                    if cursor.rowcount:
                        cursor.execute(
                            """
                            INSERT INTO resource_state_events (upload_id, state)
                            VALUES (%s, 'uploaded')
                            """,
                            (upload_id,),
                        )

        self._run("database_initialize_resource", insert)

    def get_upload(self, upload_id: UUID) -> UploadRecord:
        self.ensure_schema()

        def query() -> UploadRecord:
            with psycopg.connect(
                self.connection_string,
                connect_timeout=10,
                row_factory=dict_row,
            ) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT id, project_id, original_filename, object_key,
                               content_type, size_bytes, sha256, status,
                               b2_bucket, created_at
                        FROM uploads
                        WHERE id = %s AND status = 'stored'
                        """,
                        (upload_id,),
                    )
                    row = cursor.fetchone()
                    if row is None:
                        raise ResourceNotFoundError()
                    return self._to_record(row)

        return self._run("database_get_upload", query)

    def transition_resource(self, upload_id: UUID, state: str) -> None:
        self.ensure_schema()

        def update() -> None:
            with psycopg.connect(
                self.connection_string,
                connect_timeout=10,
            ) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE resource_readiness
                        SET lifecycle_state = %s, updated_at = NOW()
                        WHERE upload_id = %s AND removed_at IS NULL
                        """,
                        (state, upload_id),
                    )
                    if not cursor.rowcount:
                        raise ResourceNotFoundError()
                    cursor.execute(
                        """
                        INSERT INTO resource_state_events (upload_id, state)
                        VALUES (%s, %s)
                        """,
                        (upload_id, state),
                    )

        self._run("database_transition_resource", update)

    def save_readiness(
        self,
        *,
        upload_id: UUID,
        lifecycle_state: str,
        readiness_status: str,
        explanation: str,
        technical_reason: str,
        confidence: float | None,
        extracted_character_count: int,
        extracted_page_count: int | None,
        total_page_count: int | None,
        detected_language: str | None,
        duplicate_match_id: UUID | None,
        duplicate_kind: str | None,
        duplicate_similarity: float | None,
        suggested_action: str,
        content_summary: str | None,
        extracted_object_key: str | None,
        metadata_object_key: str | None,
        similarity_signature: tuple[str, ...],
    ) -> ResourceRecord:
        self.ensure_schema()

        def update() -> ResourceRecord:
            with psycopg.connect(
                self.connection_string,
                connect_timeout=10,
                row_factory=dict_row,
            ) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE resource_readiness
                        SET lifecycle_state = %s,
                            readiness_status = %s,
                            explanation = %s,
                            technical_reason = %s,
                            confidence = %s,
                            extracted_character_count = %s,
                            extracted_page_count = %s,
                            total_page_count = %s,
                            detected_language = %s,
                            duplicate_match_id = %s,
                            duplicate_kind = %s,
                            duplicate_similarity = %s,
                            suggested_action = %s,
                            content_summary = %s,
                            extracted_object_key = %s,
                            metadata_object_key = %s,
                            similarity_signature = %s,
                            approved = FALSE,
                            replacement_requested = FALSE,
                            updated_at = NOW()
                        WHERE upload_id = %s AND removed_at IS NULL
                        """,
                        (
                            lifecycle_state,
                            readiness_status,
                            explanation,
                            technical_reason,
                            confidence,
                            extracted_character_count,
                            extracted_page_count,
                            total_page_count,
                            detected_language,
                            duplicate_match_id,
                            duplicate_kind,
                            duplicate_similarity,
                            suggested_action,
                            content_summary,
                            extracted_object_key,
                            metadata_object_key,
                            list(similarity_signature),
                            upload_id,
                        ),
                    )
                    if not cursor.rowcount:
                        raise ResourceNotFoundError()
                    cursor.execute(
                        """
                        INSERT INTO resource_state_events (upload_id, state)
                        VALUES (%s, %s)
                        """,
                        (upload_id, lifecycle_state),
                    )
                    cursor.execute(
                        f"{RESOURCE_SELECT} WHERE u.id = %s",
                        (upload_id,),
                    )
                    row = cursor.fetchone()
                    if row is None:
                        raise ResourceNotFoundError()
                    return self._to_resource_record(row)

        return self._run("database_save_readiness", update)

    def get_resource(self, upload_id: UUID) -> ResourceRecord:
        self.ensure_schema()

        def query() -> ResourceRecord:
            with psycopg.connect(
                self.connection_string,
                connect_timeout=10,
                row_factory=dict_row,
            ) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"{RESOURCE_SELECT} WHERE u.id = %s",
                        (upload_id,),
                    )
                    row = cursor.fetchone()
                    if row is None:
                        raise ResourceNotFoundError()
                    return self._to_resource_record(row)

        return self._run("database_get_resource", query)

    def list_resources(
        self,
        project_id: UUID,
        *,
        include_removed: bool = False,
    ) -> list[ResourceRecord]:
        self.ensure_schema()

        def query() -> list[ResourceRecord]:
            with psycopg.connect(
                self.connection_string,
                connect_timeout=10,
                row_factory=dict_row,
            ) as connection:
                with connection.cursor() as cursor:
                    removed_filter = "" if include_removed else "AND r.removed_at IS NULL"
                    cursor.execute(
                        f"""
                        {RESOURCE_SELECT}
                        WHERE u.project_id = %s {removed_filter}
                        ORDER BY r.created_at ASC
                        """,
                        (project_id,),
                    )
                    return [
                        self._to_resource_record(row)
                        for row in cursor.fetchall()
                    ]

        return self._run("database_list_resources", query)

    def list_similarity_candidates(
        self,
        project_id: UUID,
        exclude_upload_id: UUID,
    ) -> list[ResourceRecord]:
        return [
            resource
            for resource in self.list_resources(project_id)
            if resource.id != exclude_upload_id
            and resource.similarity_signature
            and resource.readiness_status != "duplicate"
        ]

    def approve_resource(self, upload_id: UUID) -> ResourceRecord:
        return self._action_update(
            upload_id,
            set_clause=(
                "approved = TRUE, lifecycle_state = 'ready_for_analysis', "
                "replacement_requested = FALSE"
            ),
            event_state="ready_for_analysis",
        )

    def mark_for_replacement(self, upload_id: UUID) -> ResourceRecord:
        return self._action_update(
            upload_id,
            set_clause=(
                "replacement_requested = TRUE, approved = FALSE, "
                "lifecycle_state = 'replacement_requested'"
            ),
            event_state="replacement_requested",
        )

    def remove_resource(self, upload_id: UUID) -> ResourceRecord:
        return self._action_update(
            upload_id,
            set_clause="removed_at = NOW(), lifecycle_state = 'removed'",
            event_state="removed",
        )

    def _action_update(
        self,
        upload_id: UUID,
        *,
        set_clause: str,
        event_state: str,
    ) -> ResourceRecord:
        self.ensure_schema()

        def update() -> ResourceRecord:
            with psycopg.connect(
                self.connection_string,
                connect_timeout=10,
                row_factory=dict_row,
            ) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        UPDATE resource_readiness
                        SET {set_clause}, updated_at = NOW()
                        WHERE upload_id = %s
                        """,
                        (upload_id,),
                    )
                    if not cursor.rowcount:
                        raise ResourceNotFoundError()
                    cursor.execute(
                        """
                        INSERT INTO resource_state_events (upload_id, state)
                        VALUES (%s, %s)
                        """,
                        (upload_id, event_state),
                    )
                    cursor.execute(
                        f"{RESOURCE_SELECT} WHERE u.id = %s",
                        (upload_id,),
                    )
                    row = cursor.fetchone()
                    if row is None:
                        raise ResourceNotFoundError()
                    return self._to_resource_record(row)

        return self._run(f"database_{event_state}", update)
