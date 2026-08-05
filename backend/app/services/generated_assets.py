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
from typing import Callable
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
from app.models.action_pack import ActionPackCreateRequest, ActionPackResponse
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
ASSET_PROMPT_VERSION = "generated-assets-v1"
SAFE_NAME = re.compile(r"[^a-zA-Z0-9._-]+")


class AssetEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confidence: float = Field(ge=0, le=1)
    summary: str = Field(min_length=1, max_length=300)


class GoogleMediaGateway:
    """Official Gemini SDK adapter for image, TTS, and semantic evaluation."""

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

    def generate_image(self, prompt: str) -> tuple[bytes, str]:
        response = self._retry(
            lambda: self._client.models.generate_content(
                model=self._settings.gemini_image_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_modalities=["IMAGE"],
                    image_config=types.ImageConfig(aspect_ratio="16:9"),
                ),
            ),
            "gemini_visual_generation",
        )
        return _inline_media(response, "image/")

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
            if _is_quota_error(exception):
                medium = (
                    "image"
                    if operation_name == "gemini_visual_generation"
                    else "media"
                )
                raise InfrastructureError(
                    "media_quota_exhausted",
                    f"Gemini returned 429 RESOURCE_EXHAUSTED: {medium}-generation "
                    "quota is unavailable for the configured project.",
                ) from exception
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

    name = "zerobacklog-google-media"

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
        visual_topics = request.visual_topics or [pack.start_here.topic_or_resource]
        if "visual_mind_map" in request.output_options:
            for topic in visual_topics:
                facts, evidence = _topic_facts(pack, topic)
                prompt = _visual_prompt(topic, facts)
                tasks.append(
                    (
                        "visual",
                        f"visual-{_slug(topic)}",
                        f"Visual — {topic}",
                        "image/png",
                        self._settings.gemini_image_model,
                        self._get_gateway().generate_image,
                        evidence,
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
                _visual_prompt(display_name, [])
                if asset_type == "visual"
                else (
                    transcript
                    if asset_type == "voice"
                    else f"Create {display_name} from the validated Action Pack."
                )
            )
            if asset_type == "visual":
                topic = display_name.removeprefix("Visual — ")
                facts, _ = _topic_facts(pack, topic)
                prompt = _visual_prompt(topic, facts)
            settings = {
                "prompt_version": ASSET_PROMPT_VERSION,
                "voice_mode": request.voice_mode if asset_type == "voice" else None,
                "preferred_language": (
                    request.learner_profile.preferred_language
                    if request.learner_profile
                    else None
                ),
                "visual_style": "mind_map" if asset_type == "visual" else None,
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
                        "ai_generated"
                        if asset_type in {"visual", "voice"}
                        else "source_derived"
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
        if asset.asset_type not in {"note", "visual", "voice"}:
            raise ResourceActionError(
                "asset_not_regenerable",
                "Only an individual note, visual, or voice lesson can be regenerated.",
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
        elif asset.asset_type == "visual":
            topic = asset.display_name.removeprefix("Visual — ")
            facts, evidence = _topic_facts(pack, topic)
            style = request.visual_style or "mind_map"
            settings["visual_style"] = style
            prompt = _visual_prompt(topic, facts, style=style)
            generator = self._get_gateway().generate_image
            model = self._settings.gemini_image_model
            mime_type = "image/png"
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
                classification="ai_generated",
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
                    Modality.IMAGE
                    if asset_type == "visual"
                    else Modality.AUDIO
                    if asset_type == "voice"
                    else Modality.TEXT
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
            evaluation = (
                await asyncio.to_thread(
                    self._get_gateway().evaluate,
                    data,
                    actual_mime,
                    prompt[:1500],
                )
                if asset_type in {"visual", "voice"}
                else _technical_evaluation(data, actual_mime)
            )
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
    return status_code in {408, 500, 502, 503, 504} or any(
        token in type(error).__name__.lower()
        for token in ("timeout", "connection", "server")
    )


def _is_quota_error(error: Exception) -> bool:
    status_code = getattr(error, "status_code", None) or getattr(error, "code", None)
    message = str(error).upper()
    return status_code == 429 or "RESOURCE_EXHAUSTED" in message


def _safe_generation_failure(error: Exception, asset_type: str) -> str:
    current: BaseException | None = error
    while current is not None:
        if isinstance(current, InfrastructureError):
            return current.message
        if _is_quota_error(current):
            medium = "image" if asset_type == "visual" else "media"
            return (
                f"Gemini returned 429 RESOURCE_EXHAUSTED: {medium}-generation "
                "quota is unavailable for the configured project."
            )
        current = current.__cause__
    return "Generation failed before a verified asset was stored."


def _technical_evaluation(data: bytes, mime_type: str) -> AssetEvaluation:
    if not data:
        return AssetEvaluation(confidence=0, summary="The generated output was empty.")
    if mime_type.startswith("image/"):
        valid = len(data) > 20_000
    elif mime_type.startswith("audio/"):
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


def _topic_facts(pack, topic: str) -> tuple[list[str], list[dict]]:
    normalized = topic.casefold()
    for note in pack.merged_notes:
        if normalized in note.topic.casefold() or note.topic.casefold() in normalized:
            return (
                note.concise_notes[:6],
                [item.model_dump(mode="json") for item in note.evidence],
            )
    facts = [
        pack.start_here.why,
        *[
            item.explanation
            for item in pack.common_topics
            if normalized in item.topic.casefold() or item.topic.casefold() in normalized
        ],
    ]
    return facts[:6], [
        item.model_dump(mode="json") for item in pack.start_here.evidence
    ]


def _visual_prompt(
    topic: str,
    facts: list[str],
    *,
    style: str = "mind_map",
) -> str:
    fact_text = "\n".join(f"- {fact}" for fact in facts) or "- Use the topic title only."
    return (
        f"Create a polished educational {style.replace('_', ' ')} about {topic}. "
        "Use a calm navy, teal, warm coral, and cream palette. Use a clean 16:9 "
        "layout with large readable labels, strong hierarchy, arrows only where "
        "relationships are supported, and no decorative robot or generic AI imagery. "
        "Include only these verified learning points; do not add facts:\n"
        f"{fact_text}"
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
        output_options=list(record.output_options),
        action_pack=ActionPack.model_validate(record.result_json),
    )


def _slug(value: str) -> str:
    slug = SAFE_NAME.sub("-", value.strip()).strip("-").lower()
    return slug[:80] or "asset"


def _extension_for(mime_type: str) -> str:
    return {
        "application/json": "json",
        "text/markdown": "md",
        "image/png": "png",
        "image/jpeg": "jpg",
        "audio/wav": "wav",
        "audio/mpeg": "mp3",
    }.get(mime_type, "bin")
