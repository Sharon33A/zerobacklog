"""Focused contracts for personalization and generated asset handling."""

from datetime import date
from types import SimpleNamespace
from uuid import uuid4

from app.models.action_pack import ActionPackCreateRequest
from app.services.generated_assets import (
    _inline_media,
    _is_retriable_google_error,
    _render_note,
    _safe_generation_failure,
    _technical_evaluation,
)


def test_expanded_profile_and_output_selection_contract() -> None:
    request = ActionPackCreateRequest.model_validate(
        {
            "learner_profile": {
                "dsa_level": "intermediate",
                "known_topics": ["arrays"],
                "weak_topics": ["graphs"],
                "preferred_language": "English",
                "available_study_minutes_per_day": 45,
                "target_role_or_company": "Backend engineer",
                "target_interview_date": "2026-10-05",
            },
            "output_options": [
                "complete_action_pack",
                "visual_mind_map",
                "voice_lesson",
            ],
            "visual_topics": ["Graphs"],
            "voice_mode": "quick_revision",
        }
    )

    assert request.learner_profile is not None
    assert request.learner_profile.target_interview_date == date(2026, 10, 5)
    assert request.output_options[-1] == "voice_lesson"
    assert request.voice_mode == "quick_revision"


def test_inline_media_extracts_only_requested_modality() -> None:
    response = SimpleNamespace(
        candidates=[
            SimpleNamespace(
                content=SimpleNamespace(
                    parts=[
                        SimpleNamespace(
                            inline_data=SimpleNamespace(
                                data=b"png-bytes",
                                mime_type="image/png",
                            )
                        )
                    ]
                )
            )
        ]
    )

    data, mime_type = _inline_media(response, "image/")

    assert data == b"png-bytes"
    assert mime_type == "image/png"


def test_small_output_receives_transparent_low_confidence_evaluation() -> None:
    evaluation = _technical_evaluation(b"short", "image/png")

    assert evaluation.confidence < 0.72
    assert "unusually little" in evaluation.summary


def test_rendered_note_keeps_evidence_provenance() -> None:
    resource_id = uuid4()
    rendered = _render_note(
        {
            "topic": "Graphs",
            "concise_notes": ["BFS explores level by level."],
            "syntax_or_pseudocode": "queue.push(start)",
            "recognition_clues": ["Shortest unweighted path"],
            "common_mistakes": ["Forgetting visited"],
            "memory_cues": ["BFS uses a queue"],
            "evidence": [
                {
                    "resource_id": str(resource_id),
                    "title": "graphs.md",
                    "location": "BFS",
                    "confidence": 0.95,
                    "basis": "source_derived",
                    "support": "Direct note",
                }
            ],
        }
    )

    assert "BFS explores level by level." in rendered
    assert str(resource_id) in rendered
    assert "source_derived" in rendered


def test_image_quota_failure_is_exact_and_not_retried() -> None:
    error = RuntimeError("429 RESOURCE_EXHAUSTED: quota limit 0")
    error.status_code = 429

    message = _safe_generation_failure(error, "visual")

    assert message == (
        "Gemini returned 429 RESOURCE_EXHAUSTED: image-generation quota is "
        "unavailable for the configured project."
    )
    assert _is_retriable_google_error(error) is False
