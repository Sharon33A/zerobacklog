"""Genblaze-orchestrated media generation, evaluation, and immutable versions."""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import re
import time
import wave
import zipfile
from datetime import datetime, timezone
from typing import Callable, Literal
from uuid import UUID, uuid4

from genblaze_core.models.asset import Asset
from genblaze_core.models.enums import Modality
from genblaze_core.models.manifest import Manifest
from genblaze_core.pipeline.pipeline import Pipeline
from genblaze_core.pipeline.result import PipelineResult
from genblaze_core.providers.base import SyncProvider
from google import genai
from google.genai import types
from pydantic import BaseModel, ConfigDict, Field

from app.core.config import Settings
from app.core.retry import run_with_retry
from app.integrations.b2 import GenblazeB2Storage
from app.integrations.database import NeonDatabase
from app.integrations.knowledge_database import (
    AssetVersionRecord,
    GeneratedAssetRecord,
    KnowledgeDatabase,
)
from app.models.action_pack import (
    ActionPackCreateRequest,
    ActionPackResponse,
    normalize_output_options,
)
from app.models.generated_asset import (
    AssetListResponse,
    AssetProvenance,
    CompareVersionsResponse,
    GeneratedAsset,
    GeneratedAssetVersion,
    ProvenanceResource,
    RegenerateAssetRequest,
)
from app.services.errors import InfrastructureError, ResourceActionError

GENERATION_PROVIDER = "google-gemini-via-genblaze"
TEXT_PROVIDER = "zerobacklog-via-genblaze"
TEXT_MODEL = "zerobacklog-grounded-v1"
ASSET_PROMPT_VERSION = "generated-assets-v2"
SAFE_NAME = re.compile(r"[^a-zA-Z0-9._-]+")


class AssetEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confidence: float = Field(ge=0, le=1)
    summary: str = Field(min_length=1, max_length=300)


class LearningWorkflowStage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage_id: str
    label: str
    headline: str
    summary: str
    tone: Literal["teal", "blue", "violet", "amber", "coral", "green", "navy"]
    items: list[str] = Field(min_length=1)
    evidence: list[dict]
    estimated_minutes: int | None = Field(default=None, ge=0)


class LearningWorkflowAsset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    action_pack_id: UUID
    project_id: UUID
    title: str
    summary: str
    mode: Literal["guided", "concise"]
    focus_topics: list[str]
    source_ids: list[UUID]
    stages: list[LearningWorkflowStage] = Field(min_length=1)


class GoogleMediaGateway:
    """Official Gemini SDK adapter for TTS and semantic evaluation."""

    def __init__(self, settings: Settings, client=None) -> None:
        if settings.gemini_api_key is None:
            raise InfrastructureError(
                "gemini_not_configured",
                "Gemini media generation is not configured.",
            )
        self._settings = settings
        self._client = client or genai.Client(
            api_key=settings.gemini_api_key.get_secret_value()
        )

    def generate_voice(self, transcript: str) -> tuple[bytes, str]:
        response = self._retry(
            lambda: self._client.models.generate_content(
                model=self._settings.gemini_tts_model,
                contents=transcript,
                config=types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=types.SpeechConfig(
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                voice_name=self._settings.gemini_voice_name
                            )
                        )
                    ),
                ),
            ),
            "gemini_voice_generation",
        )
        pcm, _ = _inline_media(response, "audio/")
        if pcm[:4] == b"RIFF":
            return pcm, "audio/wav"
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(24_000)
            output.writeframes(pcm)
        return buffer.getvalue(), "audio/wav"

    def regenerate_note(self, prompt: str) -> tuple[bytes, str]:
        response = self._retry(
            lambda: self._client.models.generate_content(
                model=self._settings.gemini_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=(
                        "Rewrite only the supplied grounded note. Preserve every "
                        "source claim and evidence marker. Add no new facts."
                    ),
                    max_output_tokens=2_000,
                ),
            ),
            "gemini_note_regeneration",
        )
        text = (getattr(response, "text", None) or "").strip()
        if not text:
            raise InfrastructureError(
                "note_generation_failed",
                "The note regeneration returned no content.",
            )
        return text.encode("utf-8"), "text/markdown"

    def evaluate(
        self,
        data: bytes,
        mime_type: str,
        expected: str,
    ) -> AssetEvaluation:
        try:
            response = self._retry(
                lambda: self._client.models.generate_content(
                    model=self._settings.gemini_model,
                    contents=[
                        types.Part.from_bytes(data=data, mime_type=mime_type),
                        (
                            "Evaluate whether this generated learning asset is "
                            "usable, clear, and faithful to this specification: "
                            f"{expected}. Score conservatively from 0 to 1."
                        ),
                    ],
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_json_schema=AssetEvaluation.model_json_schema(),
                        max_output_tokens=500,
                    ),
                ),
                "gemini_asset_evaluation",
            )
            parsed = getattr(response, "parsed", None)
            if isinstance(parsed, AssetEvaluation):
                return parsed
            if isinstance(parsed, dict):
                return AssetEvaluation.model_validate(parsed)
            return AssetEvaluation.model_validate_json(response.text)
        except Exception:
            return _technical_evaluation(data, mime_type)

    def _retry(self, operation, operation_name: str):
        try:
            return run_with_retry(
                operation,
                operation_name=operation_name,
                attempts=self._settings.infrastructure_retry_attempts,
                is_retriable=_is_retriable_google_error,
            )
        except InfrastructureError:
            raise
        except Exception as exception:
            raise InfrastructureError(
                "media_generation_failed",
                "The selected media could not be generated.",
            ) from exception

    def close(self) -> None:
        close = getattr(self._client, "close", None)
        if callable(close):
            close()


class _StoredOutputProvider(SyncProvider):
    """Genblaze provider that generates bytes and stores the output in B2."""

    name = "zerobacklog-learning-asset"

    def __init__(
        self,
        *,
        storage: GenblazeB2Storage,
        generate: Callable[[str], tuple[bytes, str]],
        object_key: str,
        upload_id: str,
    ) -> None:
        super().__init__()
        self._storage = storage
        self._generate = generate
        self._object_key = object_key
        self._upload_id = upload_id
        self.output_data: bytes | None = None
        self.output_mime_type: str | None = None

    def generate(self, step, config=None):
        data, mime_type = self._generate(step.prompt or "")
        digest = hashlib.sha256(data).hexdigest()
        stored = self._storage.put(
            key=self._object_key,
            data=data,
            content_type=mime_type,
            upload_id=self._upload_id,
            sha256=digest,
        )
        asset = Asset(url=stored.durable_url, media_type=mime_type)
        asset.set_hash(data)
        step.assets.append(asset)
        self.output_data = data
        self.output_mime_type = mime_type
        return step


class GeneratedAssetService:
    def __init__(
        self,
        settings: Settings,
        gateway: GoogleMediaGateway | None = None,
    ) -> None:
        self._settings = settings
        self._knowledge_database = KnowledgeDatabase(settings)
        self._file_database = NeonDatabase(settings)
        self._storage = GenblazeB2Storage(settings)
        self._gateway = gateway

    def _get_gateway(self) -> GoogleMediaGateway:
        if self._gateway is None:
            self._gateway = GoogleMediaGateway(self._settings)
        return self._gateway

    async def generate_selected(
        self,
        response: ActionPackResponse,
        request: ActionPackCreateRequest,
    ) -> list[GeneratedAsset]:
        tasks: list[tuple[str, str, str, str, str, Callable[[str], tuple[bytes, str]], list]] = []
        pack = response.action_pack
        all_evidence = _all_pack_evidence(pack.model_dump(mode="json"))

        if "complete_action_pack" in request.output_options:
            payload = json.dumps(
                pack.model_dump(mode="json"), ensure_ascii=False, indent=2
            ).encode("utf-8")
            tasks.append(
                (
                    "complete_action_pack",
                    "complete",
                    "Complete Action Pack",
                    "application/json",
                    TEXT_MODEL,
                    lambda _prompt, value=payload: (value, "application/json"),
                    all_evidence,
                )
            )
        if "quick_revision_notes" in request.output_options:
            for note in pack.merged_notes:
                payload = _render_note(note.model_dump(mode="json")).encode("utf-8")
                tasks.append(
                    (
                        "note",
                        f"note-{_slug(note.topic)}",
                        f"Quick Note — {note.topic}",
                        "text/markdown",
                        TEXT_MODEL,
                        lambda _prompt, value=payload: (value, "text/markdown"),
                        [item.model_dump(mode="json") for item in note.evidence],
                    )
                )
        if "learning_workflow" in request.output_options:
            workflow = _build_learning_workflow(
                response,
                focus_topics=request.workflow_focus_topics,
                mode="guided",
            )
            payload = workflow.model_dump_json(indent=2).encode("utf-8")
            tasks.append(
                (
                    "learning_workflow",
                    "learning-workflow",
                    "Learning Workflow",
                    "application/json",
                    TEXT_MODEL,
                    lambda _prompt, value=payload: (value, "application/json"),
                    all_evidence,
                )
            )
        if "voice_lesson" in request.output_options:
            transcript = _voice_transcript(
                pack,
                quick=request.voice_mode == "quick_revision",
                preferred_language=(
                    request.learner_profile.preferred_language
                    if request.learner_profile
                    else None
                ),
            )
            tasks.append(
                (
                    "voice",
                    "voice-lesson",
                    "Voice Lesson",
                    "audio/wav",
                    self._settings.gemini_tts_model,
                    self._get_gateway().generate_voice,
                    all_evidence,
                )
            )
        if "flashcards" in request.output_options:
            payload = json.dumps(
                _flashcards(pack), ensure_ascii=False, indent=2
            ).encode("utf-8")
            tasks.append(
                (
                    "flashcards",
                    "flashcards",
                    "Flashcards",
                    "application/json",
                    TEXT_MODEL,
                    lambda _prompt, value=payload: (value, "application/json"),
                    all_evidence,
                )
            )
        if "priority_coding_problems" in request.output_options:
            payload = json.dumps(
                [item.model_dump(mode="json") for item in pack.priority_problems],
                ensure_ascii=False,
                indent=2,
            ).encode("utf-8")
            tasks.append(
                (
                    "priority_problems",
                    "priority-problems",
                    "Priority Coding Problems",
                    "application/json",
                    TEXT_MODEL,
                    lambda _prompt, value=payload: (value, "application/json"),
                    _all_pack_evidence(
                        [item.model_dump(mode="json") for item in pack.priority_problems]
                    ),
                )
            )
        if "interview_revision_sheet" in request.output_options:
            payload = _revision_sheet(pack).encode("utf-8")
            tasks.append(
                (
                    "interview_revision_sheet",
                    "interview-revision-sheet",
                    "Interview Revision Sheet",
                    "text/markdown",
                    TEXT_MODEL,
                    lambda _prompt, value=payload: (value, "text/markdown"),
                    all_evidence,
                )
            )

        for (
            asset_type,
            logical_key,
            display_name,
            mime_type,
            model,
            generator,
            evidence,
        ) in tasks:
            prompt = (
                transcript
                if asset_type == "voice"
                else f"Create {display_name} from the validated Action Pack."
            )
            settings = {
                "prompt_version": ASSET_PROMPT_VERSION,
                "voice_mode": request.voice_mode if asset_type == "voice" else None,
                "preferred_language": (
                    request.learner_profile.preferred_language
                    if request.learner_profile
                    else None
                ),
                "workflow_mode": (
                    "guided" if asset_type == "learning_workflow" else None
                ),
                "workflow_focus_topics": (
                    request.workflow_focus_topics
                    if asset_type == "learning_workflow"
                    else None
                ),
            }
            try:
                await self._generate_version(
                    response=response,
                    asset_type=asset_type,
                    logical_key=logical_key,
                    display_name=display_name,
                    mime_type=mime_type,
                    model=model,
                    prompt=prompt,
                    generator=generator,
                    evidence=evidence,
                    generation_settings=settings,
                    classification=(
                        "ai_generated" if asset_type == "voice" else "source_derived"
                    ),
                )
            except Exception:
                # Each selected asset has an independent failure record.
                continue
        return await self.list_assets(response.id)

    async def regenerate(
        self,
        asset_id: UUID,
        request: RegenerateAssetRequest,
    ) -> GeneratedAsset:
        asset, versions = await asyncio.to_thread(
            self._knowledge_database.get_asset, asset_id
        )
        if asset.asset_type not in {"note", "learning_workflow", "voice"}:
            raise ResourceActionError(
                "asset_not_regenerable",
                "Only an individual note, learning workflow, or voice lesson can "
                "be regenerated.",
            )
        pack_record = await asyncio.to_thread(
            self._knowledge_database.get_action_pack,
            asset.action_pack_id,
        )
        if pack_record.result_json is None:
            raise ResourceActionError(
                "action_pack_unavailable",
                "The originating Action Pack is unavailable.",
            )
        response = _response_from_pack_record(pack_record)
        pack = response.action_pack
        previous = versions[0] if versions else None
        settings = dict(previous.generation_settings if previous else {})
        evidence = (
            list(previous.provenance.get("evidence_references", []))
            if previous
            else _all_pack_evidence(pack.model_dump(mode="json"))
        )
        if asset.asset_type == "note":
            topic = asset.display_name.removeprefix("Quick Note — ")
            note = next(
                (item for item in pack.merged_notes if item.topic == topic),
                None,
            )
            if note is None:
                raise ResourceActionError(
                    "asset_source_unavailable",
                    "The original note is no longer available.",
                )
            base_note = _render_note(note.model_dump(mode="json"))
            prompt = (
                "Create a fresh concise revision-note version from this grounded "
                f"note. Keep the evidence footer intact.\n\n{base_note}"
            )
            generator = self._get_gateway().regenerate_note
            model = self._settings.gemini_model
            mime_type = "text/markdown"
        elif asset.asset_type == "learning_workflow":
            mode = request.workflow_mode or settings.get("workflow_mode") or "guided"
            focus_topics = [
                str(topic)
                for topic in settings.get("workflow_focus_topics", [])
                if str(topic).strip()
            ][:3]
            settings["workflow_mode"] = mode
            settings["workflow_focus_topics"] = focus_topics
            workflow = _build_learning_workflow(
                response,
                focus_topics=focus_topics,
                mode=mode,
            )
            payload = workflow.model_dump_json(indent=2).encode("utf-8")
            prompt = (
                f"Rebuild the {mode} Learning Workflow from Action Pack "
                f"{response.id}."
            )
            generator = lambda _prompt, value=payload: (
                value,
                "application/json",
            )
            model = TEXT_MODEL
            mime_type = "application/json"
            evidence = _all_pack_evidence(pack.model_dump(mode="json"))
        else:
            mode = request.voice_mode or settings.get("voice_mode") or "normal"
            settings["voice_mode"] = mode
            prompt = _voice_transcript(
                pack,
                quick=mode == "quick_revision",
                preferred_language=settings.get("preferred_language"),
            )
            generator = self._get_gateway().generate_voice
            model = self._settings.gemini_tts_model
            mime_type = "audio/wav"

        try:
            await self._generate_version(
                response=response,
                asset_type=asset.asset_type,
                logical_key=asset.logical_key,
                display_name=asset.display_name,
                mime_type=mime_type,
                model=model,
                prompt=prompt,
                generator=generator,
                evidence=evidence,
                generation_settings=settings,
                classification=(
                    "ai_generated"
                    if asset.asset_type in {"note", "voice"}
                    else "source_derived"
                ),
            )
        except Exception:
            # Return the failed version in history without moving the current
            # pointer away from the last verified stored version.
            pass
        return await self.get_asset(asset_id)

    async def _generate_version(
        self,
        *,
        response: ActionPackResponse,
        asset_type: str,
        logical_key: str,
        display_name: str,
        mime_type: str,
        model: str,
        prompt: str,
        generator: Callable[[str], tuple[bytes, str]],
        evidence: list[dict],
        generation_settings: dict,
        classification: str,
    ) -> GeneratedAssetVersion:
        asset = await asyncio.to_thread(
            self._knowledge_database.get_or_create_asset,
            asset_id=uuid4(),
            action_pack_id=response.id,
            project_id=response.project_id,
            asset_type=asset_type,
            logical_key=logical_key,
            display_name=display_name,
        )
        resources = await self._provenance_resources(
            response.project_id, evidence, response.source_ids
        )
        source_ids = tuple(resource.resource_id for resource in resources)
        now = datetime.now(timezone.utc)
        version = await asyncio.to_thread(
            self._knowledge_database.reserve_asset_version,
            version_id=uuid4(),
            asset_id=asset.id,
            provider=(
                GENERATION_PROVIDER
                if model != TEXT_MODEL
                else TEXT_PROVIDER
            ),
            model=model,
            mime_type=mime_type,
            source_ids=source_ids,
            generation_settings={
                key: value
                for key, value in generation_settings.items()
                if value is not None
            },
            provenance={
                "classification": classification,
                "resources": [
                    item.model_dump(mode="json") for item in resources
                ],
                "evidence_references": evidence,
                "generation_timestamp": now.isoformat(),
                "version_number": 1,
            },
        )
        extension = _extension_for(mime_type)
        object_key = (
            f"generated/{response.project_id}/{response.id}/{asset.id}/"
            f"v{version.version_number}/{_slug(display_name)}.{extension}"
        )
        started = time.perf_counter()
        try:
            provider = _StoredOutputProvider(
                storage=self._storage,
                generate=generator,
                object_key=object_key,
                upload_id=str(version.id),
            )
            pipeline = Pipeline(
                name=f"zerobacklog-{asset_type}-v{version.version_number}",
                project_id=str(response.project_id),
                preflight=True,
            )
            previous = await self._previous_pipeline_result(version)
            if previous is not None:
                pipeline.from_result(previous)
            pipeline.step(
                provider,
                model=model,
                prompt=prompt,
                modality=(
                    Modality.AUDIO if asset_type == "voice" else Modality.TEXT
                ),
                asset_type=asset_type,
                version_number=version.version_number,
            )
            result = await asyncio.to_thread(
                pipeline.run,
                raise_on_failure=True,
                timeout=120,
                max_retries=1,
                progress=False,
            )
            if provider.output_data is None or provider.output_mime_type is None:
                raise InfrastructureError(
                    "media_generation_failed",
                    "The generated asset contained no usable output.",
                )
            data = provider.output_data
            actual_mime = provider.output_mime_type
            if asset_type == "voice":
                evaluation = await asyncio.to_thread(
                    self._get_gateway().evaluate,
                    data,
                    actual_mime,
                    prompt[:1500],
                )
            elif asset_type == "learning_workflow":
                evaluation = _workflow_evaluation(data, actual_mime)
            else:
                evaluation = _technical_evaluation(data, actual_mime)
            manifest_payload = result.manifest.model_dump_json(
                indent=2
            ).encode("utf-8")
            manifest_key = (
                f"generated/{response.project_id}/{response.id}/{asset.id}/"
                f"v{version.version_number}/genblaze-manifest.json"
            )
            await asyncio.to_thread(
                self._storage.put,
                key=manifest_key,
                data=manifest_payload,
                content_type="application/json",
                upload_id=str(version.id),
                sha256=hashlib.sha256(manifest_payload).hexdigest(),
            )
            elapsed = round((time.perf_counter() - started) * 1000)
            completed = await asyncio.to_thread(
                self._knowledge_database.complete_asset_version,
                version.id,
                object_key=object_key,
                manifest_object_key=manifest_key,
                sha256=hashlib.sha256(data).hexdigest(),
                size_bytes=len(data),
                confidence=evaluation.confidence,
                evaluation_summary=evaluation.summary,
                generation_time_ms=elapsed,
                genblaze_run_id=result.run.run_id,
            )
            return _version_response(completed, completed.version_number)
        except Exception as exception:
            elapsed = round((time.perf_counter() - started) * 1000)
            message = _safe_generation_failure(exception, asset_type)
            await asyncio.to_thread(
                self._knowledge_database.fail_asset_version,
                version.id,
                message,
                elapsed,
            )
            raise

    async def _previous_pipeline_result(
        self,
        version: AssetVersionRecord,
    ) -> PipelineResult | None:
        if version.parent_version_number is None:
            return None
        asset, versions = await asyncio.to_thread(
            self._knowledge_database.get_asset, version.asset_id
        )
        del asset
        previous = next(
            (
                item
                for item in versions
                if item.version_number == version.parent_version_number
                and item.manifest_object_key
            ),
            None,
        )
        if previous is None or previous.manifest_object_key is None:
            return None
        try:
            payload = await asyncio.to_thread(
                self._storage.get, previous.manifest_object_key
            )
            manifest = Manifest.model_validate_json(payload)
            return PipelineResult(manifest.run, manifest)
        except Exception:
            return None

    async def _provenance_resources(
        self,
        project_id: UUID,
        evidence: list[dict],
        fallback_ids: list[UUID],
    ) -> list[ProvenanceResource]:
        evidence_map = {
            UUID(str(item["resource_id"])): str(item.get("title") or "Resource")
            for item in evidence
            if item.get("resource_id")
        }
        wanted = set(evidence_map) or set(fallback_ids)
        files, links = await asyncio.gather(
            asyncio.to_thread(self._file_database.list_resources, project_id),
            asyncio.to_thread(self._knowledge_database.list_links, project_id),
        )
        resources: list[ProvenanceResource] = []
        for item in files:
            if item.id in wanted:
                resources.append(
                    ProvenanceResource(
                        resource_id=item.id,
                        title=item.filename,
                    )
                )
        for item in links:
            if item.id in wanted:
                resources.append(
                    ProvenanceResource(
                        resource_id=item.id,
                        title=item.title,
                        link=item.url,
                    )
                )
        found = {item.resource_id for item in resources}
        for resource_id in wanted - found:
            resources.append(
                ProvenanceResource(
                    resource_id=resource_id,
                    title=evidence_map.get(resource_id, "Resource"),
                )
            )
        return sorted(resources, key=lambda item: str(item.resource_id))

    async def list_assets(self, pack_id: UUID) -> list[GeneratedAsset]:
        records = await asyncio.to_thread(
            self._knowledge_database.list_assets, pack_id
        )
        return [
            _asset_response(asset, versions)
            for asset, versions in records
        ]

    async def list_response(self, pack_id: UUID) -> AssetListResponse:
        return AssetListResponse(
            action_pack_id=pack_id,
            assets=await self.list_assets(pack_id),
        )

    async def get_asset(self, asset_id: UUID) -> GeneratedAsset:
        asset, versions = await asyncio.to_thread(
            self._knowledge_database.get_asset, asset_id
        )
        return _asset_response(asset, versions)

    async def restore(
        self,
        asset_id: UUID,
        version_number: int,
    ) -> GeneratedAsset:
        await asyncio.to_thread(
            self._knowledge_database.restore_asset_version,
            asset_id,
            version_number,
        )
        return await self.get_asset(asset_id)

    async def compare(
        self,
        asset_id: UUID,
        left: int,
        right: int,
    ) -> CompareVersionsResponse:
        asset = await self.get_asset(asset_id)
        versions = {item.version_number: item for item in asset.versions}
        if left not in versions or right not in versions:
            raise ResourceActionError(
                "asset_version_not_found",
                "One of the requested versions does not exist.",
            )
        return CompareVersionsResponse(
            asset_id=asset_id,
            left=versions[left],
            right=versions[right],
        )

    async def download_version(
        self,
        asset_id: UUID,
        version_number: int,
    ) -> tuple[bytes, str, str]:
        asset = await self.get_asset(asset_id)
        version = next(
            (item for item in asset.versions if item.version_number == version_number),
            None,
        )
        if version is None or version.status != "stored" or not version.object_key:
            raise ResourceActionError(
                "asset_version_unavailable",
                "This asset version is not available for download.",
            )
        data = await asyncio.to_thread(self._storage.get, version.object_key)
        filename = (
            f"{_slug(asset.display_name)}-v{version.version_number}."
            f"{_extension_for(version.mime_type)}"
        )
        return data, version.mime_type, filename

    async def combined_zip(self, pack_id: UUID) -> tuple[bytes, str]:
        assets = await self.list_assets(pack_id)
        buffer = io.BytesIO()
        provenance = []
        with zipfile.ZipFile(
            buffer,
            "w",
            compression=zipfile.ZIP_DEFLATED,
        ) as archive:
            for asset in assets:
                current = next(
                    (
                        item
                        for item in asset.versions
                        if item.is_current and item.status == "stored"
                    ),
                    None,
                )
                if current is None or current.object_key is None:
                    continue
                data = await asyncio.to_thread(
                    self._storage.get, current.object_key
                )
                filename = (
                    f"{_slug(asset.display_name)}-v{current.version_number}."
                    f"{_extension_for(current.mime_type)}"
                )
                archive.writestr(filename, data)
                provenance.append(
                    {
                        "asset_id": str(asset.id),
                        "asset_type": asset.asset_type,
                        "filename": filename,
                        "version": current.version_number,
                        "sha256": current.sha256,
                        "confidence": current.confidence,
                        "storage_status": current.status,
                        "provenance": current.provenance.model_dump(mode="json"),
                    }
                )
            archive.writestr(
                "provenance.json",
                json.dumps(provenance, ensure_ascii=False, indent=2),
            )
        return buffer.getvalue(), f"zerobacklog-action-pack-{pack_id}.zip"

    def close(self) -> None:
        self._storage.close()
        if self._gateway is not None:
            self._gateway.close()


def _inline_media(response, mime_prefix: str) -> tuple[bytes, str]:
    for candidate in getattr(response, "candidates", None) or []:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", None) or []:
            inline = getattr(part, "inline_data", None)
            data = getattr(inline, "data", None) if inline else None
            mime_type = getattr(inline, "mime_type", None) if inline else None
            if data and (mime_type or "").startswith(mime_prefix):
                return bytes(data), mime_type
    raise InfrastructureError(
        "media_generation_failed",
        "The media provider returned no usable asset.",
    )


def _is_retriable_google_error(error: Exception) -> bool:
    status_code = getattr(error, "status_code", None) or getattr(error, "code", None)
    return status_code in {408, 429, 500, 502, 503, 504} or any(
        token in type(error).__name__.lower()
        for token in ("timeout", "connection", "server")
    )


def _safe_generation_failure(error: Exception, asset_type: str) -> str:
    current: BaseException | None = error
    while current is not None:
        if isinstance(current, InfrastructureError):
            return current.message
        current = current.__cause__
    return (
        f"{asset_type.replace('_', ' ').title()} generation failed before a "
        "verified asset was stored."
    )


def _technical_evaluation(data: bytes, mime_type: str) -> AssetEvaluation:
    if not data:
        return AssetEvaluation(confidence=0, summary="The generated output was empty.")
    if mime_type.startswith("audio/"):
        valid = len(data) > 12_000
    else:
        valid = len(data) > 100
    return AssetEvaluation(
        confidence=0.84 if valid else 0.58,
        summary=(
            "Technical size validation passed and the asset is non-empty."
            if valid
            else "Technical validation found unusually little generated content."
        ),
    )


def _all_pack_evidence(value) -> list[dict]:
    found: list[dict] = []
    if isinstance(value, dict):
        if {"resource_id", "confidence", "basis", "support"} <= value.keys():
            found.append(value)
        else:
            for item in value.values():
                found.extend(_all_pack_evidence(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_all_pack_evidence(item))
    unique: dict[tuple[str, str | None, str], dict] = {}
    for item in found:
        key = (
            str(item.get("resource_id")),
            item.get("location"),
            str(item.get("support")),
        )
        unique[key] = item
    return list(unique.values())


def _render_note(note: dict) -> str:
    lines = [f"# {note['topic']}", "", "## Key points"]
    lines.extend(f"- {item}" for item in note["concise_notes"])
    if note.get("syntax_or_pseudocode"):
        lines.extend(
            ("", "## Syntax or pseudocode", "```", note["syntax_or_pseudocode"], "```")
        )
    for heading, key in (
        ("Recognition clues", "recognition_clues"),
        ("Common mistakes", "common_mistakes"),
        ("Memory cues", "memory_cues"),
    ):
        lines.extend(("", f"## {heading}"))
        lines.extend(f"- {item}" for item in note[key])
    lines.extend(("", "## Evidence"))
    for item in note["evidence"]:
        location = f" — {item['location']}" if item.get("location") else ""
        lines.append(
            f"- {item['title']}{location} [{item['basis']}; "
            f"{round(item['confidence'] * 100)}%] ({item['resource_id']})"
        )
    return "\n".join(lines)


def _build_learning_workflow(
    response: ActionPackResponse,
    *,
    focus_topics: list[str],
    mode: Literal["guided", "concise"],
) -> LearningWorkflowAsset:
    """Derive a learner-facing roadmap from the validated Action Pack."""
    pack = response.action_pack
    item_limit = 3 if mode == "concise" else 6
    normalized_focus = [topic.strip() for topic in focus_topics if topic.strip()][:3]

    common_topics = list(pack.common_topics)
    if normalized_focus:
        common_topics.sort(
            key=lambda item: not any(
                focus.casefold() in item.topic.casefold()
                or item.topic.casefold() in focus.casefold()
                for focus in normalized_focus
            )
        )

    core_items = [
        f"{topic.topic}: {topic.explanation}" for topic in common_topics[:item_limit]
    ] or [f"Build the foundation for {pack.start_here.topic_or_resource}."]
    core_evidence = [
        evidence.model_dump(mode="json")
        for topic in common_topics[:item_limit]
        for evidence in topic.evidence
    ]

    mistake_items = [
        f"{note.topic}: {mistake}"
        for note in pack.merged_notes
        for mistake in note.common_mistakes
    ][:item_limit]
    if not mistake_items:
        mistake_items = [
            f"{note.topic}: watch for the recognition clues before choosing a pattern."
            for note in pack.merged_notes[:item_limit]
        ] or ["Check assumptions before committing to an approach."]
    mistake_evidence = [
        evidence.model_dump(mode="json")
        for note in pack.merged_notes[:item_limit]
        for evidence in note.evidence
    ]

    priority_order = {"must_do": 0, "useful": 1, "optional": 2}
    priority_problems = sorted(
        pack.priority_problems,
        key=lambda item: priority_order[item.priority],
    )
    problem_items = [
        (
            f"{problem.priority.replace('_', ' ').title()}: "
            f"{problem.normalized_name} — {problem.reason}"
        )
        for problem in priority_problems[:item_limit]
    ] or ["Apply the core concepts to one representative problem."]
    problem_evidence = [
        evidence.model_dump(mode="json")
        for problem in priority_problems[:item_limit]
        for evidence in problem.evidence
    ]

    essential = pack.backlog_reduction.essential_resources
    practice_items = [
        f"Study {resource.title}: {resource.reason}"
        for resource in essential[: max(1, item_limit // 2)]
    ]
    practice_items.extend(
        f"Then solve {problem.normalized_name}."
        for problem in priority_problems[: max(1, item_limit // 2)]
    )
    practice_items = practice_items[:item_limit] or [
        f"Begin with {pack.start_here.topic_or_resource}, then practice immediately."
    ]
    practice_evidence = [
        evidence.model_dump(mode="json")
        for resource in essential
        for evidence in resource.evidence
    ] + problem_evidence

    revision_items = [
        f"{note.topic}: {cue}"
        for note in pack.merged_notes
        for cue in note.memory_cues
    ][:item_limit]
    revision_items.extend(
        f"Unique insight: {insight.insight}"
        for insight in pack.unique_insights[: max(0, item_limit - len(revision_items))]
    )
    revision_items = revision_items[:item_limit] or [
        "Revisit the merged notes and explain each idea without looking."
    ]
    revision_evidence = [
        evidence.model_dump(mode="json")
        for note in pack.merged_notes
        for evidence in note.evidence
    ] + [
        evidence.model_dump(mode="json")
        for insight in pack.unique_insights
        for evidence in insight.evidence
    ]

    ready_items = [
        f"Resolve this conflict: {conflict.topic}."
        for conflict in pack.contradictions[:item_limit]
    ]
    ready_items.extend(
        f"Explain {topic.topic} and when to use it."
        for topic in common_topics[: max(0, item_limit - len(ready_items))]
    )
    ready_items = ready_items[:item_limit] or [
        f"Teach back {pack.start_here.topic_or_resource} and complete a timed problem."
    ]
    ready_evidence = [
        evidence.model_dump(mode="json")
        for conflict in pack.contradictions
        for side in conflict.sides
        for evidence in side.evidence
    ] + core_evidence

    start_evidence = [
        item.model_dump(mode="json") for item in pack.start_here.evidence
    ]
    stages = [
        LearningWorkflowStage(
            stage_id="start-here",
            label="Start Here",
            headline=pack.start_here.topic_or_resource,
            summary=pack.start_here.why,
            tone="teal",
            items=[
                f"Use {resource.title}: {resource.reason}"
                for resource in essential[:item_limit]
            ]
            or [pack.start_here.why],
            evidence=start_evidence,
            estimated_minutes=pack.start_here.estimated_minutes,
        ),
        LearningWorkflowStage(
            stage_id="core-concepts",
            label="Core Concepts",
            headline="Connect the ideas that repeat",
            summary=f"{len(pack.common_topics)} recurring topic(s) shape the route.",
            tone="blue",
            items=core_items,
            evidence=core_evidence,
        ),
        LearningWorkflowStage(
            stage_id="common-mistakes",
            label="Common Mistakes",
            headline="Avoid the errors your sources warn about",
            summary="Use these checks before choosing or coding an approach.",
            tone="coral",
            items=mistake_items,
            evidence=mistake_evidence,
        ),
        LearningWorkflowStage(
            stage_id="priority-problems",
            label="Priority Problems",
            headline="Practice the highest-value problems",
            summary="Must-do problems come first; useful and optional work follows.",
            tone="violet",
            items=problem_items,
            evidence=problem_evidence,
        ),
        LearningWorkflowStage(
            stage_id="practice-order",
            label="Practice Order",
            headline="Turn reading into an ordered session",
            summary="Move from essential sources into immediate problem practice.",
            tone="amber",
            items=practice_items,
            evidence=practice_evidence,
        ),
        LearningWorkflowStage(
            stage_id="revision",
            label="Revision",
            headline="Compress the route into recall cues",
            summary="Use memory cues and rare insights to revise without rereading.",
            tone="green",
            items=revision_items,
            evidence=revision_evidence,
        ),
        LearningWorkflowStage(
            stage_id="interview-ready",
            label="Interview Ready",
            headline="Prove the learning under pressure",
            summary=pack.executive_summary,
            tone="navy",
            items=ready_items,
            evidence=ready_evidence,
        ),
    ]
    return LearningWorkflowAsset(
        action_pack_id=response.id,
        project_id=response.project_id,
        title=f"{pack.title} — Learning Workflow",
        summary=pack.executive_summary,
        mode=mode,
        focus_topics=normalized_focus,
        source_ids=response.source_ids,
        stages=stages,
    )


def _workflow_evaluation(data: bytes, mime_type: str) -> AssetEvaluation:
    if mime_type != "application/json":
        return AssetEvaluation(
            confidence=0.2,
            summary="The workflow was not returned as structured JSON.",
        )
    try:
        workflow = LearningWorkflowAsset.model_validate_json(data)
    except Exception:
        return AssetEvaluation(
            confidence=0.2,
            summary="The workflow JSON failed schema validation.",
        )
    complete = len(workflow.stages) == 7 and all(
        stage.headline.strip() and stage.items for stage in workflow.stages
    )
    return AssetEvaluation(
        confidence=0.96 if complete else 0.68,
        summary=(
            "Seven Action Pack-derived stages passed workflow validation."
            if complete
            else "The workflow is usable but one or more stages are incomplete."
        ),
    )


def _voice_transcript(pack, *, quick: bool, preferred_language: str | None) -> str:
    limit = 3 if quick else 6
    lines = [
        "ZeroBacklog voice lesson.",
        f"Start with {pack.start_here.topic_or_resource}.",
        pack.start_here.why,
    ]
    for note in pack.merged_notes[:limit]:
        lines.append(f"{note.topic}. {' '.join(note.concise_notes[:2])}")
        if note.memory_cues:
            lines.append(f"Memory cue: {note.memory_cues[0]}")
    if pack.priority_problems:
        names = ", ".join(
            item.normalized_name for item in pack.priority_problems[:4]
        )
        lines.append(f"Practice next: {names}.")
    mode = "fast, energetic revision" if quick else "calm, clear teaching"
    language = preferred_language or "English"
    return (
        f"Speak in {language} with {mode} pacing. Read the lesson naturally "
        "without announcing formatting.\n\n" + " ".join(lines)
    )


def _flashcards(pack) -> list[dict]:
    cards = []
    for note in pack.merged_notes:
        for index, point in enumerate(note.concise_notes[:2], start=1):
            cards.append(
                {
                    "front": f"{note.topic} — recall {index}",
                    "back": point,
                    "evidence": [
                        item.model_dump(mode="json") for item in note.evidence
                    ],
                }
            )
    return cards


def _revision_sheet(pack) -> str:
    lines = [
        f"# {pack.title} — Interview Revision Sheet",
        "",
        f"Start here: **{pack.start_here.topic_or_resource}**",
        "",
    ]
    for note in pack.merged_notes:
        lines.extend((f"## {note.topic}", *[f"- {item}" for item in note.concise_notes]))
        if note.common_mistakes:
            lines.append(f"- Watch for: {'; '.join(note.common_mistakes)}")
    if pack.priority_problems:
        lines.extend(("", "## Priority problems"))
        lines.extend(
            f"- [{item.priority.replace('_', ' ')}] {item.normalized_name}: {item.reason}"
            for item in pack.priority_problems
        )
    return "\n".join(lines)


def _asset_response(
    asset: GeneratedAssetRecord,
    versions: list[AssetVersionRecord],
) -> GeneratedAsset:
    return GeneratedAsset(
        id=asset.id,
        action_pack_id=asset.action_pack_id,
        project_id=asset.project_id,
        asset_type=asset.asset_type,
        logical_key=asset.logical_key,
        display_name=asset.display_name,
        current_version_number=asset.current_version_number,
        created_at=asset.created_at,
        updated_at=asset.updated_at,
        versions=[
            _version_response(item, asset.current_version_number)
            for item in versions
        ],
    )


def _version_response(
    version: AssetVersionRecord,
    current_version: int | None,
) -> GeneratedAssetVersion:
    return GeneratedAssetVersion(
        id=version.id,
        version_number=version.version_number,
        status=version.status,
        provider=version.provider,
        model=version.model,
        mime_type=version.mime_type,
        object_key=version.object_key,
        manifest_object_key=version.manifest_object_key,
        sha256=version.sha256,
        size_bytes=version.size_bytes,
        confidence=version.confidence,
        evaluation_summary=version.evaluation_summary,
        generation_time_ms=version.generation_time_ms,
        source_ids=list(version.source_ids),
        generation_settings=version.generation_settings,
        provenance=AssetProvenance.model_validate(version.provenance),
        genblaze_run_id=version.genblaze_run_id,
        parent_version_number=version.parent_version_number,
        failure_message=version.failure_message,
        created_at=version.created_at,
        is_current=version.version_number == current_version,
        download_url=(
            f"/api/v1/generated-assets/{version.asset_id}/versions/"
            f"{version.version_number}/download"
            if version.status == "stored"
            else None
        ),
    )


def _response_from_pack_record(record) -> ActionPackResponse:
    from app.models.action_pack import ActionPack

    return ActionPackResponse(
        id=record.id,
        project_id=record.project_id,
        status="completed",
        model=record.model,
        source_ids=list(record.source_ids),
        result_object_key=record.result_object_key,
        generated_at=record.updated_at,
        output_options=normalize_output_options(record.output_options),
        action_pack=ActionPack.model_validate(record.result_json),
    )


def _slug(value: str) -> str:
    slug = SAFE_NAME.sub("-", value.strip()).strip("-").lower()
    return slug[:80] or "asset"


def _extension_for(mime_type: str) -> str:
    return {
        "application/json": "json",
        "text/markdown": "md",
        "audio/wav": "wav",
        "audio/mpeg": "mp3",
    }.get(mime_type, "bin")
