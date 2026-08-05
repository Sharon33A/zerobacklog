"""Typed resource-readiness API contracts."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.integrations.database import ResourceRecord
from app.models.link import LinkReadiness

ReadinessStatus = Literal[
    "ready",
    "partial",
    "low_confidence",
    "irrelevant",
    "duplicate",
    "unreadable",
    "unsupported",
    "failed",
]


class DuplicateReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource_id: UUID
    filename: str
    kind: Literal["exact", "near"]
    similarity: float


class ResourceReadiness(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    project_id: UUID
    source_kind: Literal["file"] = "file"
    filename: str
    content_type: str
    size_bytes: int
    lifecycle_state: str
    readiness_status: ReadinessStatus | None
    explanation: str | None
    technical_reason: str | None
    confidence: float | None
    extracted_character_count: int
    extracted_page_count: int | None
    total_page_count: int | None
    detected_language: str | None
    duplicate_match: DuplicateReference | None
    suggested_action: str | None
    content_summary: str | None
    extracted_object_key: str | None
    metadata_object_key: str | None
    approved: bool
    marked_for_replacement: bool
    removed: bool
    eligible_for_analysis: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_record(cls, record: ResourceRecord) -> "ResourceReadiness":
        duplicate = None
        if (
            record.duplicate_match_id is not None
            and record.duplicate_match_filename is not None
            and record.duplicate_kind in {"exact", "near"}
            and record.duplicate_similarity is not None
        ):
            duplicate = DuplicateReference(
                resource_id=record.duplicate_match_id,
                filename=record.duplicate_match_filename,
                kind=record.duplicate_kind,
                similarity=record.duplicate_similarity,
            )
        return cls(
            id=record.id,
            project_id=record.project_id,
            filename=record.filename,
            content_type=record.content_type,
            size_bytes=record.size_bytes,
            lifecycle_state=record.lifecycle_state,
            readiness_status=record.readiness_status,
            explanation=record.explanation,
            technical_reason=record.technical_reason,
            confidence=record.confidence,
            extracted_character_count=record.extracted_character_count,
            extracted_page_count=record.extracted_page_count,
            total_page_count=record.total_page_count,
            detected_language=record.detected_language,
            duplicate_match=duplicate,
            suggested_action=record.suggested_action,
            content_summary=record.content_summary,
            extracted_object_key=record.extracted_object_key,
            metadata_object_key=record.metadata_object_key,
            approved=record.approved,
            marked_for_replacement=record.replacement_requested,
            removed=record.removed,
            eligible_for_analysis=(
                not record.removed
                and not record.replacement_requested
                and (
                    record.readiness_status == "ready"
                    or record.approved
                )
            ),
            created_at=record.created_at,
            updated_at=record.updated_at,
        )


class ResourceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource: ResourceReadiness


class ResourceListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    resources: list[ResourceReadiness]
    links: list[LinkReadiness]
    eligible_count: int
