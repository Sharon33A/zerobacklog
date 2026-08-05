"""Evidence-first Gemini knowledge reduction and Action Pack persistence."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import dataclass
from uuid import UUID, uuid4

from google import genai
from google.genai import types
from pydantic import BaseModel, ValidationError

from app.core.config import Settings
from app.core.retry import run_with_retry
from app.integrations.b2 import GenblazeB2Storage
from app.integrations.database import NeonDatabase
from app.integrations.knowledge_database import (
    ActionPackRecord,
    KnowledgeDatabase,
)
from app.models.action_pack import (
    ActionPack,
    ActionPackResponse,
    EvidenceReference,
    LearnerProfile,
    OutputOption,
)
from app.services.errors import InfrastructureError, ResourceActionError
from app.services.readiness import build_signature

PROMPT_VERSION = "knowledge-reduction-v1"
PAGE_MARKER = re.compile(r"\[Page \d+\]", re.IGNORECASE)
HEADING_MARKER = re.compile(r"^#{1,3}\s+(.+)$", re.MULTILINE)


@dataclass(frozen=True)
class SourceDocument:
    id: UUID
    title: str
    source_kind: str
    source_type: str
    content: str
    estimated_minutes: int | None
    available_locations: frozenset[str]


class GeminiGateway:
    """Small official-SDK adapter with bounded retry and typed output."""

    def __init__(self, settings: Settings, client=None) -> None:
        if settings.gemini_api_key is None:
            raise InfrastructureError(
                "gemini_not_configured",
                "Gemini analysis is not configured.",
            )
        self._settings = settings
        self._client = client or genai.Client(
            api_key=settings.gemini_api_key.get_secret_value()
        )

    def generate(self, prompt: str) -> ActionPack:
        def operation():
            return self._client.models.generate_content(
                model=self._settings.gemini_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=(
                        "You are ZeroBacklog's evidence-first knowledge reduction "
                        "engine. Compare only the supplied sources. Never invent "
                        "timestamps, pages, sections, statistics, problems, or "
                        "source claims. Use null when a location or estimate is "
                        "not supported. Every recommendation must cite supplied "
                        "resource IDs. Clearly mark AI inference in evidence basis."
                    ),
                    response_mime_type="application/json",
                    response_json_schema=ActionPack.model_json_schema(),
                    max_output_tokens=24_000,
                ),
            )

        try:
            response = run_with_retry(
                operation,
                operation_name="gemini_action_pack",
                attempts=self._settings.infrastructure_retry_attempts,
                is_retriable=_is_retriable_gemini_error,
            )
            return parse_gemini_response(response)
        except InfrastructureError:
            raise
        except ValidationError as exception:
            raise InfrastructureError(
                "gemini_invalid_output",
                "Gemini returned an Action Pack that failed schema validation.",
            ) from exception
        except Exception as exception:
            raise InfrastructureError(
                "gemini_unavailable",
                "Gemini analysis is temporarily unavailable.",
            ) from exception

    def close(self) -> None:
        close = getattr(self._client, "close", None)
        if callable(close):
            close()


def parse_gemini_response(response) -> ActionPack:
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, ActionPack):
        return parsed
    if isinstance(parsed, dict):
        return ActionPack.model_validate(parsed)
    text = getattr(response, "text", None)
    if not text:
        raise ValueError("Gemini returned no structured content.")
    return ActionPack.model_validate_json(text)


def _is_retriable_gemini_error(error: Exception) -> bool:
    status_code = getattr(error, "status_code", None) or getattr(error, "code", None)
    if status_code in {408, 429, 500, 502, 503, 504}:
        return True
    name = type(error).__name__.lower()
    return any(token in name for token in ("timeout", "connection", "server"))


class ActionPackService:
    def __init__(self, settings: Settings, gateway: GeminiGateway | None = None) -> None:
        self._settings = settings
        self._file_database = NeonDatabase(settings)
        self._knowledge_database = KnowledgeDatabase(settings)
        self._storage = GenblazeB2Storage(settings)
        self._gateway = gateway

    def _get_gateway(self) -> GeminiGateway:
        if self._gateway is None:
            self._gateway = GeminiGateway(self._settings)
        return self._gateway

    async def generate(
        self,
        project_id: UUID,
        learner_profile: LearnerProfile | None,
        output_options: list[OutputOption] | None = None,
    ) -> ActionPackResponse:
        sources = await self._collect_sources(project_id)
        if len(sources) < 2:
            raise ResourceActionError(
                "insufficient_ready_resources",
                "At least two ready or approved resources are required.",
            )

        pack_id = uuid4()
        profile_payload = (
            learner_profile.model_dump(mode="json", exclude_none=True)
            if learner_profile is not None
            else {}
        )
        await asyncio.to_thread(
            self._knowledge_database.create_action_pack,
            pack_id=pack_id,
            project_id=project_id,
            model=self._settings.gemini_model,
            prompt_version=PROMPT_VERSION,
            source_ids=tuple(source.id for source in sources),
            learner_profile=profile_payload,
            output_options=tuple(
                output_options or ["complete_action_pack"]
            ),
        )

        try:
            prompt = build_analysis_prompt(sources, profile_payload)
            generated = await asyncio.to_thread(
                self._get_gateway().generate,
                prompt,
            )
            validated = validate_action_pack(
                generated,
                sources,
                repeated_percentage=calculate_repeated_percentage(sources),
                estimated_minutes=calculate_original_minutes(sources),
            )
            result = validated.model_dump(mode="json")
            result_payload = json.dumps(
                result,
                ensure_ascii=False,
                indent=2,
            ).encode("utf-8")
            result_sha256 = hashlib.sha256(result_payload).hexdigest()
            result_key = (
                f"action-packs/{project_id}/{pack_id}/action-pack.json"
            )
            await asyncio.to_thread(
                self._storage.put,
                key=result_key,
                data=result_payload,
                content_type="application/json",
                upload_id=str(pack_id),
                sha256=result_sha256,
            )
            record = await asyncio.to_thread(
                self._knowledge_database.complete_action_pack,
                pack_id,
                result_object_key=result_key,
                result_sha256=result_sha256,
                result_json=result,
            )
            return response_from_record(record)
        except InfrastructureError as exception:
            await asyncio.to_thread(
                self._knowledge_database.fail_action_pack,
                pack_id,
                exception.code,
            )
            raise

    async def latest(self, project_id: UUID) -> ActionPackResponse:
        record = await asyncio.to_thread(
            self._knowledge_database.latest_action_pack,
            project_id,
        )
        return response_from_record(record)

    async def _collect_sources(self, project_id: UUID) -> list[SourceDocument]:
        file_records, link_records = await asyncio.gather(
            asyncio.to_thread(self._file_database.list_resources, project_id),
            asyncio.to_thread(self._knowledge_database.list_links, project_id),
        )
        sources: list[SourceDocument] = []
        total_characters = 0

        for record in file_records:
            if record.removed or record.replacement_requested:
                continue
            if record.readiness_status != "ready" and not record.approved:
                continue
            object_key = record.extracted_object_key
            if object_key is None and record.duplicate_match_id is not None:
                try:
                    match = await asyncio.to_thread(
                        self._file_database.get_resource,
                        record.duplicate_match_id,
                    )
                    object_key = match.extracted_object_key
                except Exception:
                    object_key = None
            if object_key is None:
                continue
            content = (
                await asyncio.to_thread(self._storage.get, object_key)
            ).decode("utf-8", errors="replace")
            content = self._bounded_content(content, total_characters)
            if not content:
                continue
            total_characters += len(content)
            sources.append(
                SourceDocument(
                    id=record.id,
                    title=record.filename,
                    source_kind="file",
                    source_type=record.content_type,
                    content=content,
                    estimated_minutes=estimate_reading_minutes(content),
                    available_locations=extract_locations(content),
                )
            )
            if total_characters >= self._settings.max_analysis_total_chars:
                break

        if total_characters < self._settings.max_analysis_total_chars:
            for record in link_records:
                if record.removed or (
                    record.status != "ready" and not record.approved
                ):
                    continue
                if record.snapshot_object_key is None:
                    continue
                content = (
                    await asyncio.to_thread(
                        self._storage.get,
                        record.snapshot_object_key,
                    )
                ).decode("utf-8", errors="replace")
                content = self._bounded_content(content, total_characters)
                if not content:
                    continue
                total_characters += len(content)
                sources.append(
                    SourceDocument(
                        id=record.id,
                        title=record.title,
                        source_kind="link",
                        source_type=record.source_type,
                        content=content,
                        estimated_minutes=(
                            round(record.duration_seconds / 60)
                            if record.duration_seconds is not None
                            else estimate_reading_minutes(content)
                        ),
                        available_locations=extract_locations(content),
                    )
                )
                if total_characters >= self._settings.max_analysis_total_chars:
                    break
        return sources

    def _bounded_content(self, content: str, consumed: int) -> str:
        remaining = self._settings.max_analysis_total_chars - consumed
        limit = min(self._settings.max_analysis_source_chars, remaining)
        return content[: max(0, limit)]

    def close(self) -> None:
        self._storage.close()
        if self._gateway is not None:
            self._gateway.close()


def build_analysis_prompt(
    sources: list[SourceDocument],
    learner_profile: dict,
) -> str:
    source_blocks = []
    for source in sources:
        source_blocks.append(
            "\n".join(
                (
                    f"RESOURCE_ID: {source.id}",
                    f"TITLE: {source.title}",
                    f"KIND: {source.source_kind}",
                    f"TYPE: {source.source_type}",
                    "AVAILABLE_LOCATIONS: "
                    + (", ".join(sorted(source.available_locations)) or "none"),
                    "CONTENT:",
                    source.content,
                )
            )
        )
    profile = (
        json.dumps(learner_profile, ensure_ascii=False)
        if learner_profile
        else "No learner profile supplied; produce a complete general pack."
    )
    return (
        "Build the first ZeroBacklog Action Pack from all supplied resources. "
        "Reduce repeated material, select one Start Here recommendation, compare "
        "common and unique ideas, report genuine conflicts only, merge concise "
        "topic notes, and normalize coding problems only when named in sources. "
        "Do not claim a transcript for YouTube metadata. Do not cite a location "
        "unless it appears in AVAILABLE_LOCATIONS. Use source_derived for direct "
        "claims and ai_inferred for synthesis or personalization. If no conflict "
        "or coding problem is evidenced, return an empty list for that section.\n\n"
        f"LEARNER_PROFILE:\n{profile}\n\n"
        "SOURCES:\n\n"
        + "\n\n--- NEXT RESOURCE ---\n\n".join(source_blocks)
    )


def validate_action_pack(
    pack: ActionPack,
    sources: list[SourceDocument],
    *,
    repeated_percentage: float,
    estimated_minutes: int | None,
) -> ActionPack:
    checked = pack.model_copy(deep=True)
    source_map = {source.id: source for source in sources}
    for evidence in iter_evidence(checked):
        source = source_map.get(evidence.resource_id)
        if source is None:
            raise InfrastructureError(
                "gemini_invalid_evidence",
                "Gemini referenced a resource outside the analysis set.",
            )
        evidence.title = source.title
        if (
            evidence.location is not None
            and evidence.location not in source.available_locations
        ):
            evidence.location = None

    for choice in (
        checked.backlog_reduction.essential_resources
        + checked.backlog_reduction.optional_resources
        + checked.backlog_reduction.skippable_resources
    ):
        source = source_map.get(choice.resource_id)
        if source is None:
            raise InfrastructureError(
                "gemini_invalid_evidence",
                "Gemini returned a verdict for an unknown resource.",
            )
        choice.title = source.title
    for verdict in checked.resource_verdicts:
        source = source_map.get(verdict.resource_id)
        if source is None:
            raise InfrastructureError(
                "gemini_invalid_evidence",
                "Gemini returned a verdict for an unknown resource.",
            )
        verdict.title = source.title
    for topic in checked.common_topics:
        unique_sources = {item.resource_id for item in topic.evidence}
        if len(unique_sources) < 2:
            raise InfrastructureError(
                "gemini_invalid_evidence",
                "A common topic did not cite multiple resources.",
            )
        topic.source_count = len(unique_sources)
    for problem in checked.priority_problems:
        problem.source_count = len(
            {item.resource_id for item in problem.evidence}
        )

    checked.backlog_reduction.resource_count = len(sources)
    checked.backlog_reduction.repeated_content_percentage = repeated_percentage
    checked.backlog_reduction.estimated_original_minutes = estimated_minutes
    checked.backlog_reduction.metric_methodology = (
        "Server-calculated from normalized three-token shingle overlap and "
        "source duration or a 200-words-per-minute reading estimate."
    )
    return ActionPack.model_validate(checked.model_dump())


def iter_evidence(value) -> list[EvidenceReference]:
    found: list[EvidenceReference] = []
    if isinstance(value, EvidenceReference):
        return [value]
    if isinstance(value, BaseModel):
        for field_name in value.__class__.model_fields:
            found.extend(iter_evidence(getattr(value, field_name)))
    elif isinstance(value, list):
        for item in value:
            found.extend(iter_evidence(item))
    return found


def extract_locations(content: str) -> frozenset[str]:
    locations = set(PAGE_MARKER.findall(content))
    locations.update(match.strip() for match in HEADING_MARKER.findall(content))
    return frozenset(locations)


def estimate_reading_minutes(content: str) -> int:
    words = len(content.split())
    return max(1, round(words / 200))


def calculate_original_minutes(sources: list[SourceDocument]) -> int | None:
    estimates = [
        source.estimated_minutes
        for source in sources
        if source.estimated_minutes is not None
    ]
    return sum(estimates) if estimates else None


def calculate_repeated_percentage(sources: list[SourceDocument]) -> float:
    signatures = [set(build_signature(source.content)) for source in sources]
    all_shingles = set().union(*signatures)
    if not all_shingles:
        return 0.0
    repeated = sum(
        sum(shingle in signature for signature in signatures) > 1
        for shingle in all_shingles
    )
    return round(repeated / len(all_shingles) * 100, 1)


def response_from_record(record: ActionPackRecord) -> ActionPackResponse:
    if (
        record.status != "completed"
        or record.result_json is None
        or record.result_object_key is None
    ):
        raise InfrastructureError(
            "action_pack_unavailable",
            "The Action Pack is not available.",
        )
    return ActionPackResponse(
        id=record.id,
        project_id=record.project_id,
        status="completed",
        model=record.model,
        source_ids=list(record.source_ids),
        result_object_key=record.result_object_key,
        generated_at=record.updated_at,
        action_pack=ActionPack.model_validate(record.result_json),
        output_options=list(record.output_options),
    )
