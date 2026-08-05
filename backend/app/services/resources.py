"""Resource extraction and readiness orchestration."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from uuid import UUID

from app.core.config import Settings
from app.integrations.b2 import GenblazeB2Storage
from app.integrations.database import NeonDatabase, ResourceRecord
from app.services.errors import InfrastructureError, ResourceActionError
from app.services.extraction import ExtractionResult, extract_resource
from app.services.readiness import (
    DuplicateMatch,
    ReadinessDecision,
    build_signature,
    decide_readiness,
    similarity_score,
)

logger = logging.getLogger(__name__)
NEAR_DUPLICATE_THRESHOLD = 0.80


class ResourceService:
    def __init__(self, settings: Settings) -> None:
        self._database = NeonDatabase(settings)
        self._storage = GenblazeB2Storage(settings)

    async def process(self, resource_id: UUID) -> ResourceRecord:
        upload = await asyncio.to_thread(self._database.get_upload, resource_id)
        await asyncio.to_thread(
            self._database.initialize_resource,
            resource_id,
            upload.project_id,
        )
        await asyncio.to_thread(
            self._database.transition_resource,
            resource_id,
            "validating",
        )

        exact = await asyncio.to_thread(
            self._database.find_by_sha256,
            upload.sha256,
            upload.project_id,
            resource_id,
        )
        if exact is not None:
            decision = decide_readiness(
                None,
                exact_duplicate=DuplicateMatch(
                    resource_id=exact.id,
                    filename=exact.original_filename,
                    kind="exact",
                    similarity=1.0,
                ),
            )
            return await self._persist_result(
                upload=upload,
                extraction=None,
                decision=decision,
            )

        try:
            await asyncio.to_thread(
                self._database.transition_resource,
                resource_id,
                "extracting",
            )
            source = await asyncio.to_thread(
                self._storage.get,
                upload.object_key,
            )
            extraction = await asyncio.to_thread(
                extract_resource,
                upload.original_filename,
                source,
            )
            await asyncio.to_thread(
                self._database.transition_resource,
                resource_id,
                "classified",
            )
            near_match = await self._find_near_duplicate(
                upload.project_id,
                upload.id,
                extraction,
            )
            decision = decide_readiness(
                extraction,
                near_duplicate=near_match,
            )
            return await self._persist_result(
                upload=upload,
                extraction=extraction,
                decision=decision,
            )
        except InfrastructureError:
            await self._best_effort_failed_status(
                upload.id,
                "An infrastructure dependency interrupted processing.",
            )
            raise
        except Exception:
            logger.exception(
                "Resource processing failed resource_id=%s",
                resource_id,
            )
            return await self._save_failed(
                upload.id,
                "The extractor encountered an unexpected resource-level error.",
            )

    async def _find_near_duplicate(
        self,
        project_id: UUID,
        resource_id: UUID,
        extraction: ExtractionResult,
    ) -> DuplicateMatch | None:
        signature = build_signature(extraction.text)
        if not signature:
            return None
        candidates = await asyncio.to_thread(
            self._database.list_similarity_candidates,
            project_id,
            resource_id,
        )
        best: DuplicateMatch | None = None
        for candidate in candidates:
            score = similarity_score(signature, candidate.similarity_signature)
            if score < NEAR_DUPLICATE_THRESHOLD:
                continue
            if best is None or score > best.similarity:
                best = DuplicateMatch(
                    resource_id=candidate.id,
                    filename=candidate.filename,
                    kind="near",
                    similarity=round(score, 4),
                )
        return best

    async def _persist_result(
        self,
        *,
        upload,
        extraction: ExtractionResult | None,
        decision: ReadinessDecision,
    ) -> ResourceRecord:
        derived_prefix = f"derived/{upload.id}"
        extracted_key = (
            f"{derived_prefix}/extracted.txt"
            if extraction is not None and extraction.text
            else None
        )
        metadata_key = f"{derived_prefix}/readiness.json"

        if extracted_key is not None and extraction is not None:
            extracted_bytes = extraction.text.encode("utf-8")
            await asyncio.to_thread(
                self._storage.put,
                key=extracted_key,
                data=extracted_bytes,
                content_type="text/plain; charset=utf-8",
                upload_id=str(upload.id),
                sha256=hashlib.sha256(extracted_bytes).hexdigest(),
            )

        metadata = {
            "schema_version": 1,
            "resource_id": str(upload.id),
            "project_id": str(upload.project_id),
            "source_object_key": upload.object_key,
            "readiness_status": decision.status,
            "explanation": decision.explanation,
            "technical_reason": decision.technical_reason,
            "confidence": decision.confidence,
            "extracted_character_count": (
                extraction.character_count if extraction is not None else 0
            ),
            "extracted_page_count": (
                extraction.extracted_pages if extraction is not None else None
            ),
            "total_page_count": (
                extraction.total_pages if extraction is not None else None
            ),
            "detected_language": (
                extraction.detected_language if extraction is not None else None
            ),
            "duplicate_match_id": (
                str(decision.duplicate.resource_id)
                if decision.duplicate is not None
                else None
            ),
            "duplicate_kind": (
                decision.duplicate.kind if decision.duplicate is not None else None
            ),
            "duplicate_similarity": (
                decision.duplicate.similarity
                if decision.duplicate is not None
                else None
            ),
            "suggested_action": decision.suggested_action,
            "extracted_object_key": extracted_key,
        }
        metadata_bytes = json.dumps(
            metadata,
            ensure_ascii=False,
            indent=2,
        ).encode("utf-8")
        try:
            await asyncio.to_thread(
                self._storage.put,
                key=metadata_key,
                data=metadata_bytes,
                content_type="application/json",
                upload_id=str(upload.id),
                sha256=hashlib.sha256(metadata_bytes).hexdigest(),
            )
        except InfrastructureError:
            if extracted_key is not None:
                await asyncio.to_thread(self._storage.delete, extracted_key)
            raise

        lifecycle = (
            "ready_for_analysis" if decision.status == "ready" else decision.status
        )
        return await asyncio.to_thread(
            self._database.save_readiness,
            upload_id=upload.id,
            lifecycle_state=lifecycle,
            readiness_status=decision.status,
            explanation=decision.explanation,
            technical_reason=decision.technical_reason,
            confidence=decision.confidence,
            extracted_character_count=(
                extraction.character_count if extraction is not None else 0
            ),
            extracted_page_count=(
                extraction.extracted_pages if extraction is not None else None
            ),
            total_page_count=(
                extraction.total_pages if extraction is not None else None
            ),
            detected_language=(
                extraction.detected_language if extraction is not None else None
            ),
            duplicate_match_id=(
                decision.duplicate.resource_id
                if decision.duplicate is not None
                else None
            ),
            duplicate_kind=(
                decision.duplicate.kind if decision.duplicate is not None else None
            ),
            duplicate_similarity=(
                decision.duplicate.similarity
                if decision.duplicate is not None
                else None
            ),
            suggested_action=decision.suggested_action,
            content_summary=decision.content_summary,
            extracted_object_key=extracted_key,
            metadata_object_key=metadata_key,
            similarity_signature=decision.signature,
        )

    async def _save_failed(
        self,
        resource_id: UUID,
        technical_reason: str,
    ) -> ResourceRecord:
        return await asyncio.to_thread(
            self._database.save_readiness,
            upload_id=resource_id,
            lifecycle_state="failed",
            readiness_status="failed",
            explanation="Failed — this resource could not be processed.",
            technical_reason=technical_reason,
            confidence=None,
            extracted_character_count=0,
            extracted_page_count=None,
            total_page_count=None,
            detected_language=None,
            duplicate_match_id=None,
            duplicate_kind=None,
            duplicate_similarity=None,
            suggested_action="Retry processing or replace this resource.",
            content_summary=None,
            extracted_object_key=None,
            metadata_object_key=None,
            similarity_signature=(),
        )

    async def _best_effort_failed_status(
        self,
        resource_id: UUID,
        technical_reason: str,
    ) -> None:
        try:
            await self._save_failed(resource_id, technical_reason)
        except Exception:
            return

    async def get(self, resource_id: UUID) -> ResourceRecord:
        return await asyncio.to_thread(self._database.get_resource, resource_id)

    async def list(self, project_id: UUID) -> list[ResourceRecord]:
        return await asyncio.to_thread(
            self._database.list_resources,
            project_id,
        )

    async def remove(self, resource_id: UUID) -> ResourceRecord:
        return await asyncio.to_thread(
            self._database.remove_resource,
            resource_id,
        )

    async def approve(self, resource_id: UUID) -> ResourceRecord:
        resource = await self.get(resource_id)
        if resource.removed:
            raise ResourceActionError(
                "resource_removed",
                "A removed resource cannot be included.",
            )
        if resource.readiness_status not in {"duplicate", "irrelevant"}:
            raise ResourceActionError(
                "resource_not_approvable",
                "Only duplicate or irrelevant resources need Include Anyway.",
            )
        return await asyncio.to_thread(
            self._database.approve_resource,
            resource_id,
        )

    async def mark_for_replacement(self, resource_id: UUID) -> ResourceRecord:
        resource = await self.get(resource_id)
        if resource.removed:
            raise ResourceActionError(
                "resource_removed",
                "A removed resource cannot be replaced.",
            )
        return await asyncio.to_thread(
            self._database.mark_for_replacement,
            resource_id,
        )

    def close(self) -> None:
        self._storage.close()
