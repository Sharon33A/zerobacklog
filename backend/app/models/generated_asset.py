"""Typed contracts for generated media, provenance, and immutable versions."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

AssetType = Literal[
    "complete_action_pack",
    "note",
    "visual",
    "voice",
    "flashcards",
    "priority_problems",
    "interview_revision_sheet",
]


class ProvenanceResource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource_id: UUID
    title: str
    link: str | None = None


class AssetProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    classification: Literal["source_derived", "ai_generated", "ai_inferred"]
    resources: list[ProvenanceResource]
    evidence_references: list[dict[str, Any]]
    generation_timestamp: datetime
    version_number: int = Field(ge=1)


class GeneratedAssetVersion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    version_number: int = Field(ge=1)
    status: Literal["generating", "stored", "failed"]
    provider: str
    model: str
    mime_type: str
    object_key: str | None
    manifest_object_key: str | None
    sha256: str | None
    size_bytes: int | None
    confidence: float | None = Field(default=None, ge=0, le=1)
    evaluation_summary: str | None
    generation_time_ms: int | None = Field(default=None, ge=0)
    source_ids: list[UUID]
    generation_settings: dict[str, Any]
    provenance: AssetProvenance
    genblaze_run_id: str | None
    parent_version_number: int | None
    failure_message: str | None
    created_at: datetime
    is_current: bool = False
    download_url: str | None = None


class GeneratedAsset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    action_pack_id: UUID
    project_id: UUID
    asset_type: AssetType
    logical_key: str
    display_name: str
    current_version_number: int | None
    created_at: datetime
    updated_at: datetime
    versions: list[GeneratedAssetVersion] = Field(default_factory=list)


class AssetListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_pack_id: UUID
    assets: list[GeneratedAsset]


class RegenerateAssetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    voice_mode: Literal["normal", "quick_revision"] | None = None
    visual_style: Literal[
        "mind_map",
        "flow_diagram",
        "algorithm_flow",
        "comparison_chart",
    ] | None = None


class CompareVersionsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: UUID
    left: GeneratedAssetVersion
    right: GeneratedAssetVersion
