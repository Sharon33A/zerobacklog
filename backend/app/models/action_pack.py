"""Evidence-first Action Pack contracts used by Gemini and the API."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.generated_asset import GeneratedAsset

OutputOption = Literal[
    "complete_action_pack",
    "quick_revision_notes",
    "visual_mind_map",
    "voice_lesson",
    "flashcards",
    "priority_coding_problems",
    "interview_revision_sheet",
]


class EvidenceReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource_id: UUID
    title: str
    location: str | None = None
    confidence: float = Field(ge=0, le=1)
    basis: Literal["source_derived", "ai_inferred"]
    support: str


class ResourceChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource_id: UUID
    title: str
    reason: str
    evidence: list[EvidenceReference] = Field(min_length=1)


class BacklogReduction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource_count: int = Field(ge=2)
    estimated_original_minutes: int | None = Field(default=None, ge=0)
    repeated_content_percentage: float = Field(ge=0, le=100)
    metric_methodology: str
    essential_resources: list[ResourceChoice]
    optional_resources: list[ResourceChoice]
    skippable_resources: list[ResourceChoice]


class StartHere(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic_or_resource: str
    why: str
    estimated_minutes: int | None = Field(default=None, ge=0)
    evidence: list[EvidenceReference] = Field(min_length=1)


class CommonTopic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str
    explanation: str
    source_count: int = Field(ge=2)
    evidence: list[EvidenceReference] = Field(min_length=2)


class UniqueInsight(BaseModel):
    model_config = ConfigDict(extra="forbid")

    insight: str
    why_it_matters: str
    evidence: list[EvidenceReference] = Field(min_length=1)


class ConflictSide(BaseModel):
    model_config = ConfigDict(extra="forbid")

    position: str
    evidence: list[EvidenceReference] = Field(min_length=1)


class Contradiction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str
    sides: list[ConflictSide] = Field(min_length=2)
    neutral_explanation: str
    recommendation: str | None
    recommendation_confidence: float | None = Field(default=None, ge=0, le=1)


class ResourceVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource_id: UUID
    title: str
    verdict: Literal[
        "essential",
        "use_selected_sections",
        "reference_only",
        "safe_to_skip",
        "unavailable_or_low_confidence",
    ]
    reason: str
    selected_sections: list[str]
    evidence: list[EvidenceReference] = Field(min_length=1)


class MergedNote(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str
    concise_notes: list[str] = Field(min_length=1)
    syntax_or_pseudocode: str | None
    recognition_clues: list[str]
    common_mistakes: list[str]
    memory_cues: list[str]
    evidence: list[EvidenceReference] = Field(min_length=1)


class PriorityProblem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    normalized_name: str
    aliases: list[str]
    priority: Literal["must_do", "useful", "optional"]
    reason: str
    source_count: int = Field(ge=1)
    evidence: list[EvidenceReference] = Field(min_length=1)


class ActionPack(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    executive_summary: str
    backlog_reduction: BacklogReduction
    start_here: StartHere
    common_topics: list[CommonTopic]
    unique_insights: list[UniqueInsight]
    contradictions: list[Contradiction]
    resource_verdicts: list[ResourceVerdict]
    merged_notes: list[MergedNote]
    priority_problems: list[PriorityProblem]


class LearnerProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dsa_level: Literal["beginner", "intermediate", "advanced"] | None = None
    known_topics: list[str] = Field(default_factory=list, max_length=30)
    weak_topics: list[str] = Field(default_factory=list, max_length=30)
    preferred_language: str | None = Field(default=None, max_length=50)
    target_role_or_company: str | None = Field(default=None, max_length=120)
    available_study_minutes_per_day: int | None = Field(
        default=None,
        ge=10,
        le=1440,
    )
    target_interview_date: date | None = None


class ActionPackCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    learner_profile: LearnerProfile | None = None
    output_options: list[OutputOption] = Field(
        default_factory=lambda: ["complete_action_pack"],
        min_length=1,
        max_length=7,
    )
    visual_topics: list[str] = Field(default_factory=list, max_length=3)
    voice_mode: Literal["normal", "quick_revision"] = "normal"


class ActionPackResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    project_id: UUID
    status: Literal["completed"]
    model: str
    source_ids: list[UUID]
    result_object_key: str
    generated_at: datetime
    action_pack: ActionPack
    output_options: list[OutputOption] = Field(
        default_factory=lambda: ["complete_action_pack"]
    )
    assets: list[GeneratedAsset] = Field(default_factory=list)
