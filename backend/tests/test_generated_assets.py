"""Focused contracts for personalization and generated asset handling."""

from datetime import date
from types import SimpleNamespace
from uuid import uuid4

from app.models.action_pack import ActionPackCreateRequest
from app.services.generated_assets import (
    _inline_media,
    _is_retriable_google_error,
    _render_note,
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
                "learning_workflow",
                "voice_lesson",
            ],
            "workflow_focus_topics": ["Graphs"],
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
                                data=b"audio-bytes",
                                mime_type="audio/wav",
                            )
                        )
                    ]
                )
            )
        ]
    )

    data, mime_type = _inline_media(response, "audio/")

    assert data == b"audio-bytes"
    assert mime_type == "audio/wav"


def test_small_output_receives_transparent_low_confidence_evaluation() -> None:
    evaluation = _technical_evaluation(b"short", "application/json")

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


def test_transient_provider_throttling_is_a_retry_candidate() -> None:
    error = RuntimeError("provider temporarily throttled")
    error.status_code = 429

    assert _is_retriable_google_error(error) is True
