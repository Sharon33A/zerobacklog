"""Typed public-link intake contracts."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field

from app.integrations.knowledge_database import LinkRecord

LinkStatus = Literal[
    "processing",
    "ready",
    "partial",
    "inaccessible",
    "irrelevant",
    "failed",
]


class LinkCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    url: AnyHttpUrl


class LinkReadiness(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    project_id: UUID
    source_kind: Literal["link"] = "link"
    url: str
    source_type: str
    title: str
    description: str | None
    author: str | None
    duration_seconds: int | None
    outbound_links: list[str]
    status: LinkStatus
    explanation: str
    technical_reason: str
    confidence: float | None
    extracted_character_count: int
    snapshot_object_key: str | None
    metadata_object_key: str | None
    content_summary: str | None
    approved: bool
    removed: bool
    eligible_for_analysis: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_record(cls, record: LinkRecord) -> "LinkReadiness":
        return cls(
            id=record.id,
            project_id=record.project_id,
            url=record.url,
            source_type=record.source_type,
            title=record.title,
            description=record.description,
            author=record.author,
            duration_seconds=record.duration_seconds,
            outbound_links=list(record.outbound_links),
            status=record.status,
            explanation=record.explanation,
            technical_reason=record.technical_reason,
            confidence=record.confidence,
            extracted_character_count=record.extracted_character_count,
            snapshot_object_key=record.snapshot_object_key,
            metadata_object_key=record.metadata_object_key,
            content_summary=record.content_summary,
            approved=record.approved,
            removed=record.removed,
            eligible_for_analysis=(
                not record.removed
                and bool(record.snapshot_object_key)
                and (record.status == "ready" or record.approved)
            ),
            created_at=record.created_at,
            updated_at=record.updated_at,
        )


class LinkResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    link: LinkReadiness


class LinkList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    links: list[LinkReadiness] = Field(default_factory=list)
