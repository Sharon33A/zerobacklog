"""Public-link intake orchestration across retrieval, B2, and Neon."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from uuid import UUID, uuid4

from app.core.config import Settings
from app.integrations.b2 import GenblazeB2Storage
from app.integrations.knowledge_database import KnowledgeDatabase, LinkRecord
from app.services.errors import InfrastructureError, ResourceActionError
from app.services.link_intake import (
    LinkSnapshot,
    retrieve_link,
    validate_link,
)

logger = logging.getLogger(__name__)


class LinkService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._database = KnowledgeDatabase(settings)
        self._storage = GenblazeB2Storage(settings)

    async def create(self, project_id: UUID, url: str) -> LinkRecord:
        validated = validate_link(url)
        existing = await asyncio.to_thread(
            self._database.find_link,
            project_id,
            validated.normalized_url,
        )
        if existing is not None:
            return existing
        link_id = uuid4()
        await asyncio.to_thread(
            self._database.create_link,
            link_id=link_id,
            project_id=project_id,
            url=validated.original_url,
            normalized_url=validated.normalized_url,
            source_type=validated.source_type,
        )
        return await self._process(link_id, validated)

    async def process(self, link_id: UUID) -> LinkRecord:
        record = await asyncio.to_thread(self._database.get_link, link_id)
        validated = validate_link(record.normalized_url)
        return await self._process(link_id, validated)

    async def _process(self, link_id: UUID, validated) -> LinkRecord:
        youtube_key = (
            self._settings.youtube_api_key.get_secret_value()
            if self._settings.youtube_api_key is not None
            else None
        )
        try:
            snapshot = await asyncio.to_thread(
                retrieve_link,
                validated,
                youtube_api_key=youtube_key,
                max_bytes=self._settings.max_link_snapshot_bytes,
            )
            return await self._persist(
                link_id=link_id,
                validated=validated,
                snapshot=snapshot,
            )
        except InfrastructureError:
            raise
        except Exception:
            logger.exception("Link processing failed link_id=%s", link_id)
            failed = LinkSnapshot(
                title=validated.hostname,
                description=None,
                author=None,
                duration_seconds=None,
                outbound_links=(),
                text="",
                status="failed",
                explanation="Failed — this link could not be processed.",
                technical_reason="An unexpected link-processing error occurred.",
                confidence=None,
                summary=None,
            )
            return await self._persist(
                link_id=link_id,
                validated=validated,
                snapshot=failed,
            )

    async def _persist(
        self,
        *,
        link_id: UUID,
        validated,
        snapshot: LinkSnapshot,
    ) -> LinkRecord:
        prefix = f"links/{link_id}"
        snapshot_key = f"{prefix}/snapshot.txt" if snapshot.text else None
        metadata_key = f"{prefix}/metadata.json"
        if snapshot_key:
            payload = snapshot.text.encode("utf-8")
            await asyncio.to_thread(
                self._storage.put,
                key=snapshot_key,
                data=payload,
                content_type="text/plain; charset=utf-8",
                upload_id=str(link_id),
                sha256=hashlib.sha256(payload).hexdigest(),
            )
        metadata = {
            "schema_version": 1,
            "link_id": str(link_id),
            "url": validated.normalized_url,
            "source_type": validated.source_type,
            "title": snapshot.title,
            "description": snapshot.description,
            "author": snapshot.author,
            "duration_seconds": snapshot.duration_seconds,
            "outbound_links": list(snapshot.outbound_links),
            "status": snapshot.status,
            "explanation": snapshot.explanation,
            "technical_reason": snapshot.technical_reason,
            "confidence": snapshot.confidence,
            "snapshot_object_key": snapshot_key,
        }
        metadata_payload = json.dumps(
            metadata,
            indent=2,
            ensure_ascii=False,
        ).encode("utf-8")
        try:
            await asyncio.to_thread(
                self._storage.put,
                key=metadata_key,
                data=metadata_payload,
                content_type="application/json",
                upload_id=str(link_id),
                sha256=hashlib.sha256(metadata_payload).hexdigest(),
            )
        except InfrastructureError:
            if snapshot_key:
                await asyncio.to_thread(self._storage.delete, snapshot_key)
            raise
        return await asyncio.to_thread(
            self._database.save_link,
            link_id,
            title=snapshot.title,
            description=snapshot.description,
            author=snapshot.author,
            duration_seconds=snapshot.duration_seconds,
            outbound_links=snapshot.outbound_links,
            status=snapshot.status,
            explanation=snapshot.explanation,
            technical_reason=snapshot.technical_reason,
            confidence=snapshot.confidence,
            extracted_character_count=len(snapshot.text),
            snapshot_object_key=snapshot_key,
            metadata_object_key=metadata_key,
            content_summary=snapshot.summary,
        )

    async def list(self, project_id: UUID) -> list[LinkRecord]:
        return await asyncio.to_thread(self._database.list_links, project_id)

    async def get(self, link_id: UUID) -> LinkRecord:
        return await asyncio.to_thread(self._database.get_link, link_id)

    async def approve(self, link_id: UUID) -> LinkRecord:
        record = await self.get(link_id)
        if record.status not in {"partial", "irrelevant"}:
            raise ResourceActionError(
                "link_not_approvable",
                "Only partial or irrelevant links need Include Anyway.",
            )
        if not record.snapshot_object_key:
            raise ResourceActionError(
                "link_has_no_content",
                "This link has no retrieved content to include.",
            )
        return await asyncio.to_thread(self._database.approve_link, link_id)

    async def remove(self, link_id: UUID) -> LinkRecord:
        return await asyncio.to_thread(self._database.remove_link, link_id)

    def close(self) -> None:
        self._storage.close()
