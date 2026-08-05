"""Neon persistence for link intake and generated Action Packs."""

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
class LinkRecord:
    id: UUID
    project_id: UUID
    url: str
    normalized_url: str
    source_type: str
    title: str
    description: str | None
    author: str | None
    duration_seconds: int | None
    outbound_links: tuple[str, ...]
    status: str
    explanation: str
    technical_reason: str
    confidence: float | None
    extracted_character_count: int
    snapshot_object_key: str | None
    metadata_object_key: str | None
    content_summary: str | None
    approved: bool
    removed: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class ActionPackRecord:
    id: UUID
    project_id: UUID
    status: str
    model: str
    prompt_version: str
    source_ids: tuple[UUID, ...]
    learner_profile: dict
    output_options: tuple[str, ...]
    result_object_key: str | None
    result_sha256: str | None
    result_json: dict | None
    failure_code: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class GeneratedAssetRecord:
    id: UUID
    action_pack_id: UUID
    project_id: UUID
    asset_type: str
    logical_key: str
    display_name: str
    current_version_number: int | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class AssetVersionRecord:
    id: UUID
    asset_id: UUID
    version_number: int
    status: str
    provider: str
    model: str
    mime_type: str
    object_key: str | None
    manifest_object_key: str | None
    sha256: str | None
    size_bytes: int | None
    confidence: float | None
    evaluation_summary: str | None
    generation_time_ms: int | None
    source_ids: tuple[UUID, ...]
    generation_settings: dict
    provenance: dict
    genblaze_run_id: str | None
    parent_version_number: int | None
    failure_message: str | None
    created_at: datetime


class KnowledgeDatabase:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._schema_ready = False
        self._schema_lock = threading.Lock()

    @property
    def connection_string(self) -> str:
        if self._settings.database_url is None:
            raise InfrastructureError(
                "database_not_configured",
                "Knowledge metadata storage is not configured.",
            )
        return self._settings.database_url.get_secret_value()

    def _run(self, operation_name: str, operation):
        try:
            return run_with_retry(
                operation,
                operation_name=operation_name,
                attempts=self._settings.infrastructure_retry_attempts,
                is_retriable=lambda error: isinstance(
                    error,
                    (psycopg.OperationalError, psycopg.InterfaceError),
                ),
            )
        except InfrastructureError:
            raise
        except psycopg.Error as exception:
            raise InfrastructureError(
                "database_unavailable",
                "Knowledge metadata storage is currently unavailable.",
            ) from exception

    def ensure_schema(self) -> None:
        if self._schema_ready:
            return
        with self._schema_lock:
            if self._schema_ready:
                return

            def create() -> None:
                with psycopg.connect(
                    self.connection_string,
                    connect_timeout=10,
                ) as connection:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            """
                            CREATE TABLE IF NOT EXISTS link_resources (
                                id UUID PRIMARY KEY,
                                project_id UUID NOT NULL,
                                url TEXT NOT NULL,
                                normalized_url TEXT NOT NULL,
                                source_type TEXT NOT NULL,
                                title TEXT NOT NULL,
                                description TEXT,
                                author TEXT,
                                duration_seconds INTEGER CHECK (
                                    duration_seconds IS NULL OR duration_seconds >= 0
                                ),
                                outbound_links JSONB NOT NULL DEFAULT '[]'::jsonb,
                                status TEXT NOT NULL CHECK (
                                    status IN (
                                        'processing', 'ready', 'partial',
                                        'inaccessible', 'irrelevant', 'failed'
                                    )
                                ),
                                explanation TEXT NOT NULL,
                                technical_reason TEXT NOT NULL,
                                confidence DOUBLE PRECISION CHECK (
                                    confidence IS NULL OR
                                    (confidence >= 0 AND confidence <= 1)
                                ),
                                extracted_character_count INTEGER NOT NULL DEFAULT 0,
                                snapshot_object_key TEXT,
                                metadata_object_key TEXT,
                                content_summary TEXT,
                                approved BOOLEAN NOT NULL DEFAULT FALSE,
                                removed_at TIMESTAMPTZ,
                                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                                UNIQUE (project_id, normalized_url)
                            )
                            """
                        )
                        cursor.execute(
                            """
                            CREATE INDEX IF NOT EXISTS link_resources_project_idx
                            ON link_resources (project_id, created_at)
                            """
                        )
                        cursor.execute(
                            """
                            CREATE TABLE IF NOT EXISTS action_packs (
                                id UUID PRIMARY KEY,
                                project_id UUID NOT NULL,
                                status TEXT NOT NULL CHECK (
                                    status IN ('generating', 'completed', 'failed')
                                ),
                                model TEXT NOT NULL,
                                prompt_version TEXT NOT NULL,
                                source_ids UUID[] NOT NULL,
                                learner_profile JSONB NOT NULL DEFAULT '{}'::jsonb,
                                result_object_key TEXT,
                                result_sha256 CHAR(64),
                                result_json JSONB,
                                failure_code TEXT,
                                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                            )
                            """
                        )
                        cursor.execute(
                            """
                            CREATE INDEX IF NOT EXISTS action_packs_project_idx
                            ON action_packs (project_id, created_at DESC)
                            """
                        )
                        cursor.execute(
                            """
                            ALTER TABLE action_packs
                            ADD COLUMN IF NOT EXISTS output_options TEXT[]
                            NOT NULL DEFAULT ARRAY['complete_action_pack']::TEXT[]
                            """
                        )
                        cursor.execute(
                            """
                            CREATE TABLE IF NOT EXISTS generated_assets (
                                id UUID PRIMARY KEY,
                                action_pack_id UUID NOT NULL,
                                project_id UUID NOT NULL,
                                asset_type TEXT NOT NULL CHECK (
                                    asset_type IN (
                                        'complete_action_pack', 'note', 'visual',
                                        'voice', 'flashcards', 'priority_problems',
                                        'interview_revision_sheet'
                                    )
                                ),
                                logical_key TEXT NOT NULL,
                                display_name TEXT NOT NULL,
                                current_version_number INTEGER,
                                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                                UNIQUE (action_pack_id, asset_type, logical_key)
                            )
                            """
                        )
                        cursor.execute(
                            """
                            CREATE TABLE IF NOT EXISTS generated_asset_versions (
                                id UUID PRIMARY KEY,
                                asset_id UUID NOT NULL REFERENCES generated_assets(id),
                                version_number INTEGER NOT NULL CHECK (
                                    version_number > 0
                                ),
                                status TEXT NOT NULL CHECK (
                                    status IN ('generating', 'stored', 'failed')
                                ),
                                provider TEXT NOT NULL,
                                model TEXT NOT NULL,
                                mime_type TEXT NOT NULL,
                                object_key TEXT,
                                manifest_object_key TEXT,
                                sha256 CHAR(64),
                                size_bytes BIGINT,
                                confidence DOUBLE PRECISION CHECK (
                                    confidence IS NULL OR
                                    (confidence >= 0 AND confidence <= 1)
                                ),
                                evaluation_summary TEXT,
                                generation_time_ms INTEGER,
                                source_ids UUID[] NOT NULL,
                                generation_settings JSONB NOT NULL,
                                provenance JSONB NOT NULL,
                                genblaze_run_id TEXT,
                                parent_version_number INTEGER,
                                failure_message TEXT,
                                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                                UNIQUE (asset_id, version_number)
                            )
                            """
                        )
                        cursor.execute(
                            """
                            CREATE INDEX IF NOT EXISTS generated_assets_pack_idx
                            ON generated_assets (action_pack_id, created_at)
                            """
                        )

            self._run("knowledge_schema", create)
            self._schema_ready = True

    @staticmethod
    def _link(row: dict) -> LinkRecord:
        return LinkRecord(
            id=row["id"],
            project_id=row["project_id"],
            url=row["url"],
            normalized_url=row["normalized_url"],
            source_type=row["source_type"],
            title=row["title"],
            description=row["description"],
            author=row["author"],
            duration_seconds=row["duration_seconds"],
            outbound_links=tuple(row["outbound_links"] or ()),
            status=row["status"],
            explanation=row["explanation"],
            technical_reason=row["technical_reason"],
            confidence=row["confidence"],
            extracted_character_count=row["extracted_character_count"],
            snapshot_object_key=row["snapshot_object_key"],
            metadata_object_key=row["metadata_object_key"],
            content_summary=row["content_summary"],
            approved=row["approved"],
            removed=row["removed_at"] is not None,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _pack(row: dict) -> ActionPackRecord:
        return ActionPackRecord(
            id=row["id"],
            project_id=row["project_id"],
            status=row["status"],
            model=row["model"],
            prompt_version=row["prompt_version"],
            source_ids=tuple(row["source_ids"]),
            learner_profile=row["learner_profile"] or {},
            output_options=tuple(
                row.get("output_options") or ("complete_action_pack",)
            ),
            result_object_key=row["result_object_key"],
            result_sha256=row["result_sha256"],
            result_json=row["result_json"],
            failure_code=row["failure_code"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _asset(row: dict) -> GeneratedAssetRecord:
        return GeneratedAssetRecord(
            id=row["id"],
            action_pack_id=row["action_pack_id"],
            project_id=row["project_id"],
            asset_type=row["asset_type"],
            logical_key=row["logical_key"],
            display_name=row["display_name"],
            current_version_number=row["current_version_number"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _asset_version(row: dict) -> AssetVersionRecord:
        return AssetVersionRecord(
            id=row["id"],
            asset_id=row["asset_id"],
            version_number=row["version_number"],
            status=row["status"],
            provider=row["provider"],
            model=row["model"],
            mime_type=row["mime_type"],
            object_key=row["object_key"],
            manifest_object_key=row["manifest_object_key"],
            sha256=row["sha256"],
            size_bytes=row["size_bytes"],
            confidence=row["confidence"],
            evaluation_summary=row["evaluation_summary"],
            generation_time_ms=row["generation_time_ms"],
            source_ids=tuple(row["source_ids"] or ()),
            generation_settings=row["generation_settings"] or {},
            provenance=row["provenance"] or {},
            genblaze_run_id=row["genblaze_run_id"],
            parent_version_number=row["parent_version_number"],
            failure_message=row["failure_message"],
            created_at=row["created_at"],
        )

    def find_link(self, project_id: UUID, normalized_url: str) -> LinkRecord | None:
        self.ensure_schema()

        def query() -> LinkRecord | None:
            with psycopg.connect(
                self.connection_string,
                connect_timeout=10,
                row_factory=dict_row,
            ) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT * FROM link_resources
                        WHERE project_id = %s AND normalized_url = %s
                              AND removed_at IS NULL
                        """,
                        (project_id, normalized_url),
                    )
                    row = cursor.fetchone()
                    return self._link(row) if row else None

        return self._run("database_find_link", query)

    def create_link(
        self,
        *,
        link_id: UUID,
        project_id: UUID,
        url: str,
        normalized_url: str,
        source_type: str,
    ) -> LinkRecord:
        self.ensure_schema()

        def insert() -> LinkRecord:
            with psycopg.connect(
                self.connection_string,
                connect_timeout=10,
                row_factory=dict_row,
            ) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO link_resources (
                            id, project_id, url, normalized_url, source_type,
                            title, status, explanation, technical_reason
                        )
                        VALUES (
                            %s, %s, %s, %s, %s, %s, 'processing',
                            'Validating this public link.',
                            'Metadata retrieval is in progress.'
                        )
                        RETURNING *
                        """,
                        (
                            link_id,
                            project_id,
                            url,
                            normalized_url,
                            source_type,
                            normalized_url,
                        ),
                    )
                    return self._link(cursor.fetchone())

        try:
            return self._run("database_create_link", insert)
        except InfrastructureError:
            existing = self.find_link(project_id, normalized_url)
            if existing is not None:
                return existing
            raise

    def save_link(
        self,
        link_id: UUID,
        *,
        title: str,
        description: str | None,
        author: str | None,
        duration_seconds: int | None,
        outbound_links: tuple[str, ...],
        status: str,
        explanation: str,
        technical_reason: str,
        confidence: float | None,
        extracted_character_count: int,
        snapshot_object_key: str | None,
        metadata_object_key: str | None,
        content_summary: str | None,
    ) -> LinkRecord:
        self.ensure_schema()

        def update() -> LinkRecord:
            with psycopg.connect(
                self.connection_string,
                connect_timeout=10,
                row_factory=dict_row,
            ) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE link_resources
                        SET title = %s, description = %s, author = %s,
                            duration_seconds = %s, outbound_links = %s::jsonb,
                            status = %s, explanation = %s,
                            technical_reason = %s, confidence = %s,
                            extracted_character_count = %s,
                            snapshot_object_key = %s,
                            metadata_object_key = %s,
                            content_summary = %s,
                            approved = FALSE,
                            updated_at = NOW()
                        WHERE id = %s AND removed_at IS NULL
                        RETURNING *
                        """,
                        (
                            title,
                            description,
                            author,
                            duration_seconds,
                            psycopg.types.json.Jsonb(list(outbound_links)),
                            status,
                            explanation,
                            technical_reason,
                            confidence,
                            extracted_character_count,
                            snapshot_object_key,
                            metadata_object_key,
                            content_summary,
                            link_id,
                        ),
                    )
                    row = cursor.fetchone()
                    if row is None:
                        raise ResourceNotFoundError()
                    return self._link(row)

        return self._run("database_save_link", update)

    def get_link(self, link_id: UUID) -> LinkRecord:
        self.ensure_schema()

        def query() -> LinkRecord:
            with psycopg.connect(
                self.connection_string,
                connect_timeout=10,
                row_factory=dict_row,
            ) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT * FROM link_resources WHERE id = %s",
                        (link_id,),
                    )
                    row = cursor.fetchone()
                    if row is None:
                        raise ResourceNotFoundError()
                    return self._link(row)

        return self._run("database_get_link", query)

    def list_links(self, project_id: UUID) -> list[LinkRecord]:
        self.ensure_schema()

        def query() -> list[LinkRecord]:
            with psycopg.connect(
                self.connection_string,
                connect_timeout=10,
                row_factory=dict_row,
            ) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT * FROM link_resources
                        WHERE project_id = %s AND removed_at IS NULL
                        ORDER BY created_at ASC
                        """,
                        (project_id,),
                    )
                    return [self._link(row) for row in cursor.fetchall()]

        return self._run("database_list_links", query)

    def approve_link(self, link_id: UUID) -> LinkRecord:
        return self._link_action(
            link_id,
            "approved = TRUE, updated_at = NOW()",
        )

    def remove_link(self, link_id: UUID) -> LinkRecord:
        return self._link_action(
            link_id,
            "removed_at = NOW(), updated_at = NOW()",
        )

    def _link_action(self, link_id: UUID, set_clause: str) -> LinkRecord:
        self.ensure_schema()

        def update() -> LinkRecord:
            with psycopg.connect(
                self.connection_string,
                connect_timeout=10,
                row_factory=dict_row,
            ) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        UPDATE link_resources SET {set_clause}
                        WHERE id = %s RETURNING *
                        """,
                        (link_id,),
                    )
                    row = cursor.fetchone()
                    if row is None:
                        raise ResourceNotFoundError()
                    return self._link(row)

        return self._run("database_link_action", update)

    def create_action_pack(
        self,
        *,
        pack_id: UUID,
        project_id: UUID,
        model: str,
        prompt_version: str,
        source_ids: tuple[UUID, ...],
        learner_profile: dict,
        output_options: tuple[str, ...],
    ) -> ActionPackRecord:
        self.ensure_schema()

        def insert() -> ActionPackRecord:
            with psycopg.connect(
                self.connection_string,
                connect_timeout=10,
                row_factory=dict_row,
            ) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO action_packs (
                            id, project_id, status, model, prompt_version,
                            source_ids, learner_profile, output_options
                        )
                        VALUES (%s, %s, 'generating', %s, %s, %s, %s, %s)
                        RETURNING *
                        """,
                        (
                            pack_id,
                            project_id,
                            model,
                            prompt_version,
                            list(source_ids),
                            psycopg.types.json.Jsonb(learner_profile),
                            list(output_options),
                        ),
                    )
                    return self._pack(cursor.fetchone())

        return self._run("database_create_action_pack", insert)

    def complete_action_pack(
        self,
        pack_id: UUID,
        *,
        result_object_key: str,
        result_sha256: str,
        result_json: dict,
    ) -> ActionPackRecord:
        return self._update_pack(
            pack_id,
            status="completed",
            result_object_key=result_object_key,
            result_sha256=result_sha256,
            result_json=result_json,
            failure_code=None,
        )

    def fail_action_pack(self, pack_id: UUID, failure_code: str) -> None:
        try:
            self._update_pack(
                pack_id,
                status="failed",
                result_object_key=None,
                result_sha256=None,
                result_json=None,
                failure_code=failure_code,
            )
        except InfrastructureError:
            return

    def _update_pack(
        self,
        pack_id: UUID,
        *,
        status: str,
        result_object_key: str | None,
        result_sha256: str | None,
        result_json: dict | None,
        failure_code: str | None,
    ) -> ActionPackRecord:
        self.ensure_schema()

        def update() -> ActionPackRecord:
            with psycopg.connect(
                self.connection_string,
                connect_timeout=10,
                row_factory=dict_row,
            ) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE action_packs
                        SET status = %s, result_object_key = %s,
                            result_sha256 = %s, result_json = %s,
                            failure_code = %s, updated_at = NOW()
                        WHERE id = %s
                        RETURNING *
                        """,
                        (
                            status,
                            result_object_key,
                            result_sha256,
                            psycopg.types.json.Jsonb(result_json)
                            if result_json is not None
                            else None,
                            failure_code,
                            pack_id,
                        ),
                    )
                    row = cursor.fetchone()
                    if row is None:
                        raise ResourceNotFoundError()
                    return self._pack(row)

        return self._run("database_update_action_pack", update)

    def latest_action_pack(self, project_id: UUID) -> ActionPackRecord:
        self.ensure_schema()

        def query() -> ActionPackRecord:
            with psycopg.connect(
                self.connection_string,
                connect_timeout=10,
                row_factory=dict_row,
            ) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT * FROM action_packs
                        WHERE project_id = %s AND status = 'completed'
                        ORDER BY created_at DESC
                        LIMIT 1
                        """,
                        (project_id,),
                    )
                    row = cursor.fetchone()
                    if row is None:
                        raise ResourceNotFoundError()
                    return self._pack(row)

        return self._run("database_latest_action_pack", query)

    def get_action_pack(self, pack_id: UUID) -> ActionPackRecord:
        self.ensure_schema()

        def query() -> ActionPackRecord:
            with psycopg.connect(
                self.connection_string,
                connect_timeout=10,
                row_factory=dict_row,
            ) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT * FROM action_packs WHERE id = %s",
                        (pack_id,),
                    )
                    row = cursor.fetchone()
                    if row is None:
                        raise ResourceNotFoundError()
                    return self._pack(row)

        return self._run("database_get_action_pack", query)

    def get_or_create_asset(
        self,
        *,
        asset_id: UUID,
        action_pack_id: UUID,
        project_id: UUID,
        asset_type: str,
        logical_key: str,
        display_name: str,
    ) -> GeneratedAssetRecord:
        self.ensure_schema()

        def upsert() -> GeneratedAssetRecord:
            with psycopg.connect(
                self.connection_string,
                connect_timeout=10,
                row_factory=dict_row,
            ) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO generated_assets (
                            id, action_pack_id, project_id, asset_type,
                            logical_key, display_name
                        )
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (action_pack_id, asset_type, logical_key)
                        DO UPDATE SET display_name = EXCLUDED.display_name,
                                      updated_at = NOW()
                        RETURNING *
                        """,
                        (
                            asset_id,
                            action_pack_id,
                            project_id,
                            asset_type,
                            logical_key,
                            display_name,
                        ),
                    )
                    return self._asset(cursor.fetchone())

        return self._run("database_get_or_create_asset", upsert)

    def reserve_asset_version(
        self,
        *,
        version_id: UUID,
        asset_id: UUID,
        provider: str,
        model: str,
        mime_type: str,
        source_ids: tuple[UUID, ...],
        generation_settings: dict,
        provenance: dict,
    ) -> AssetVersionRecord:
        self.ensure_schema()

        def reserve() -> AssetVersionRecord:
            with psycopg.connect(
                self.connection_string,
                connect_timeout=10,
                row_factory=dict_row,
            ) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT id FROM generated_assets WHERE id = %s FOR UPDATE",
                        (asset_id,),
                    )
                    if cursor.fetchone() is None:
                        raise ResourceNotFoundError()
                    cursor.execute(
                        """
                        SELECT COALESCE(MAX(version_number), 0) + 1 AS next_version
                        FROM generated_asset_versions WHERE asset_id = %s
                        """,
                        (asset_id,),
                    )
                    version_number = cursor.fetchone()["next_version"]
                    version_provenance = {
                        **provenance,
                        "version_number": version_number,
                    }
                    cursor.execute(
                        """
                        INSERT INTO generated_asset_versions (
                            id, asset_id, version_number, status, provider, model,
                            mime_type, source_ids, generation_settings,
                            provenance, parent_version_number
                        )
                        VALUES (
                            %s, %s, %s, 'generating', %s, %s, %s, %s, %s, %s,
                            NULLIF(%s - 1, 0)
                        )
                        RETURNING *
                        """,
                        (
                            version_id,
                            asset_id,
                            version_number,
                            provider,
                            model,
                            mime_type,
                            list(source_ids),
                            psycopg.types.json.Jsonb(generation_settings),
                            psycopg.types.json.Jsonb(version_provenance),
                            version_number,
                        ),
                    )
                    return self._asset_version(cursor.fetchone())

        return self._run("database_reserve_asset_version", reserve)

    def complete_asset_version(
        self,
        version_id: UUID,
        *,
        object_key: str,
        manifest_object_key: str,
        sha256: str,
        size_bytes: int,
        confidence: float,
        evaluation_summary: str,
        generation_time_ms: int,
        genblaze_run_id: str,
    ) -> AssetVersionRecord:
        self.ensure_schema()

        def complete() -> AssetVersionRecord:
            with psycopg.connect(
                self.connection_string,
                connect_timeout=10,
                row_factory=dict_row,
            ) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE generated_asset_versions
                        SET status = 'stored', object_key = %s,
                            manifest_object_key = %s, sha256 = %s,
                            size_bytes = %s, confidence = %s,
                            evaluation_summary = %s, generation_time_ms = %s,
                            genblaze_run_id = %s
                        WHERE id = %s
                        RETURNING *
                        """,
                        (
                            object_key,
                            manifest_object_key,
                            sha256,
                            size_bytes,
                            confidence,
                            evaluation_summary,
                            generation_time_ms,
                            genblaze_run_id,
                            version_id,
                        ),
                    )
                    row = cursor.fetchone()
                    if row is None:
                        raise ResourceNotFoundError()
                    record = self._asset_version(row)
                    cursor.execute(
                        """
                        UPDATE generated_assets
                        SET current_version_number = %s, updated_at = NOW()
                        WHERE id = %s
                        """,
                        (record.version_number, record.asset_id),
                    )
                    return record

        return self._run("database_complete_asset_version", complete)

    def fail_asset_version(
        self,
        version_id: UUID,
        failure_message: str,
        generation_time_ms: int,
    ) -> None:
        self.ensure_schema()

        def fail() -> None:
            with psycopg.connect(
                self.connection_string,
                connect_timeout=10,
            ) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE generated_asset_versions
                        SET status = 'failed', failure_message = %s,
                            generation_time_ms = %s
                        WHERE id = %s
                        """,
                        (failure_message[:500], generation_time_ms, version_id),
                    )

        self._run("database_fail_asset_version", fail)

    def list_assets(
        self,
        action_pack_id: UUID,
    ) -> list[tuple[GeneratedAssetRecord, list[AssetVersionRecord]]]:
        self.ensure_schema()

        def query():
            with psycopg.connect(
                self.connection_string,
                connect_timeout=10,
                row_factory=dict_row,
            ) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT * FROM generated_assets
                        WHERE action_pack_id = %s
                        ORDER BY created_at, display_name
                        """,
                        (action_pack_id,),
                    )
                    assets = [self._asset(row) for row in cursor.fetchall()]
                    result = []
                    for asset in assets:
                        cursor.execute(
                            """
                            SELECT * FROM generated_asset_versions
                            WHERE asset_id = %s ORDER BY version_number DESC
                            """,
                            (asset.id,),
                        )
                        result.append(
                            (
                                asset,
                                [
                                    self._asset_version(row)
                                    for row in cursor.fetchall()
                                ],
                            )
                        )
                    return result

        return self._run("database_list_assets", query)

    def get_asset(
        self,
        asset_id: UUID,
    ) -> tuple[GeneratedAssetRecord, list[AssetVersionRecord]]:
        self.ensure_schema()

        def query():
            with psycopg.connect(
                self.connection_string,
                connect_timeout=10,
                row_factory=dict_row,
            ) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT * FROM generated_assets WHERE id = %s",
                        (asset_id,),
                    )
                    row = cursor.fetchone()
                    if row is None:
                        raise ResourceNotFoundError()
                    asset = self._asset(row)
                    cursor.execute(
                        """
                        SELECT * FROM generated_asset_versions
                        WHERE asset_id = %s ORDER BY version_number DESC
                        """,
                        (asset_id,),
                    )
                    return asset, [
                        self._asset_version(item) for item in cursor.fetchall()
                    ]

        return self._run("database_get_asset", query)

    def restore_asset_version(
        self,
        asset_id: UUID,
        version_number: int,
    ) -> GeneratedAssetRecord:
        self.ensure_schema()

        def restore() -> GeneratedAssetRecord:
            with psycopg.connect(
                self.connection_string,
                connect_timeout=10,
                row_factory=dict_row,
            ) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT 1 FROM generated_asset_versions
                        WHERE asset_id = %s AND version_number = %s
                              AND status = 'stored'
                        """,
                        (asset_id, version_number),
                    )
                    if cursor.fetchone() is None:
                        raise ResourceNotFoundError()
                    cursor.execute(
                        """
                        UPDATE generated_assets
                        SET current_version_number = %s, updated_at = NOW()
                        WHERE id = %s RETURNING *
                        """,
                        (version_number, asset_id),
                    )
                    row = cursor.fetchone()
                    if row is None:
                        raise ResourceNotFoundError()
                    return self._asset(row)

        return self._run("database_restore_asset_version", restore)
