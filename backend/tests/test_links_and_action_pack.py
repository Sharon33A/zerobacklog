"""Focused URL-intake and evidence-first Action Pack tests."""

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.action_pack import ActionPack, ActionPackResponse
from app.services.action_packs import (
    SourceDocument,
    parse_gemini_response,
    validate_action_pack,
)
from app.services.errors import InfrastructureError, UrlValidationError
from app.services.generated_assets import (
    _build_learning_workflow,
    _workflow_evaluation,
)
from app.services.link_intake import (
    parse_iso_duration,
    retrieve_link,
    validate_link,
)
from app.core.logging import redact_sensitive_text


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://youtu.be/abcdefghijk", "youtube"),
        ("https://github.com/openai/openai-python", "github_repository"),
        ("https://leetcode.com/problemset/", "coding_platform"),
        ("https://neetcode.io/roadmap", "coding_sheet"),
        ("https://docs.python.org/3/library/", "documentation"),
        ("https://example.com/coding-guide", "website"),
    ],
)
def test_url_validation_and_source_classification(url: str, expected: str) -> None:
    validated = validate_link(url)

    assert validated.source_type == expected
    assert "#" not in validated.normalized_url


def test_private_url_is_rejected() -> None:
    with pytest.raises(UrlValidationError) as error:
        validate_link("http://127.0.0.1/admin")

    assert error.value.code == "unsafe_url"


def test_youtube_duration_parsing() -> None:
    assert parse_iso_duration("PT1H2M3S") == 3723
    assert parse_iso_duration("not-a-duration") is None


def test_youtube_metadata_is_partial_without_promising_transcript(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.services.link_intake._safe_get_json",
        lambda *_args, **_kwargs: {
            "items": [
                {
                    "snippet": {
                        "title": "Graph Algorithms for Interviews",
                        "description": (
                            "Learn graphs and BFS. https://example.com/sheet"
                        ),
                        "channelTitle": "DSA Classroom",
                    },
                    "contentDetails": {"duration": "PT12M30S"},
                    "status": {"privacyStatus": "public"},
                }
            ]
        },
    )

    snapshot = retrieve_link(
        validate_link("https://youtu.be/abcdefghijk"),
        youtube_api_key="test-only-key",
        max_bytes=1024,
    )

    assert snapshot.status == "partial"
    assert snapshot.duration_seconds == 750
    assert snapshot.author == "DSA Classroom"
    assert snapshot.outbound_links == ("https://example.com/sheet",)
    assert snapshot.status == "partial"
    assert snapshot.explanation == (
        "Metadata processed. Spoken video content was not analyzed because "
        "no transcript was available."
    )


def test_query_api_keys_are_redacted_from_logs() -> None:
    logged = redact_sensitive_text(
        "GET https://example.com/data?part=snippet&key=super-secret-value&id=1"
    )

    assert "super-secret-value" not in logged
    assert "key=[REDACTED]" in logged


def _pack_payload(first_id, second_id) -> dict:
    evidence = {
        "resource_id": str(first_id),
        "title": "Invented title",
        "location": "Invented section",
        "confidence": 0.9,
        "basis": "source_derived",
        "support": "Arrays and binary search are directly discussed.",
    }
    return {
        "title": "DSA Backlog Reduction",
        "executive_summary": "Start with arrays, then use the second resource.",
        "backlog_reduction": {
            "resource_count": 2,
            "estimated_original_minutes": 999,
            "repeated_content_percentage": 99,
            "metric_methodology": "Model estimate",
            "essential_resources": [
                {
                    "resource_id": str(first_id),
                    "title": "Wrong",
                    "reason": "Contains the foundation.",
                    "evidence": [evidence],
                }
            ],
            "optional_resources": [],
            "skippable_resources": [],
        },
        "start_here": {
            "topic_or_resource": "Arrays",
            "why": "Both fundamentals build from indexed access.",
            "estimated_minutes": 20,
            "evidence": [evidence],
        },
        "common_topics": [
            {
                "topic": "Arrays",
                "explanation": "Both sources discuss array operations.",
                "source_count": 99,
                "evidence": [
                    evidence,
                    {
                        **evidence,
                        "resource_id": str(second_id),
                        "title": "Second",
                    },
                ],
            }
        ],
        "unique_insights": [],
        "contradictions": [],
        "resource_verdicts": [],
        "merged_notes": [],
        "priority_problems": [],
    }


def test_gemini_output_parsing_with_mock_response() -> None:
    first_id, second_id = uuid4(), uuid4()
    response = SimpleNamespace(
        parsed=None,
        text=json.dumps(_pack_payload(first_id, second_id)),
    )

    parsed = parse_gemini_response(response)

    assert isinstance(parsed, ActionPack)
    assert parsed.start_here.topic_or_resource == "Arrays"


def test_learning_workflow_is_derived_from_the_action_pack() -> None:
    first_id, second_id = uuid4(), uuid4()
    pack = ActionPack.model_validate(_pack_payload(first_id, second_id))
    response = ActionPackResponse(
        id=uuid4(),
        project_id=uuid4(),
        status="completed",
        model="test-model",
        source_ids=[first_id, second_id],
        result_object_key="action-packs/test/action-pack.json",
        generated_at=datetime.now(timezone.utc),
        action_pack=pack,
        output_options=["learning_workflow"],
    )

    workflow = _build_learning_workflow(
        response,
        focus_topics=["Arrays"],
        mode="guided",
    )
    payload = workflow.model_dump_json().encode("utf-8")
    evaluation = _workflow_evaluation(payload, "application/json")

    assert len(workflow.stages) == 7
    assert workflow.stages[0].headline == "Arrays"
    assert any(
        "Arrays" in item for item in workflow.stages[1].items
    )
    assert workflow.source_ids == [first_id, second_id]
    assert evaluation.confidence == 0.96


def test_evidence_references_are_validated_and_metrics_are_server_owned() -> None:
    first_id, second_id = uuid4(), uuid4()
    pack = ActionPack.model_validate(_pack_payload(first_id, second_id))
    sources = [
        SourceDocument(
            id=first_id,
            title="arrays.md",
            source_kind="file",
            source_type="text/markdown",
            content="## Arrays\nBinary search on sorted arrays.",
            estimated_minutes=3,
            available_locations=frozenset({"Arrays"}),
        ),
        SourceDocument(
            id=second_id,
            title="searching.txt",
            source_kind="file",
            source_type="text/plain",
            content="Arrays and searching interview practice.",
            estimated_minutes=2,
            available_locations=frozenset(),
        ),
    ]

    checked = validate_action_pack(
        pack,
        sources,
        repeated_percentage=12.5,
        estimated_minutes=5,
    )

    assert checked.backlog_reduction.resource_count == 2
    assert checked.backlog_reduction.repeated_content_percentage == 12.5
    assert checked.backlog_reduction.estimated_original_minutes == 5
    assert checked.start_here.evidence[0].title == "arrays.md"
    assert checked.start_here.evidence[0].location is None
    assert checked.common_topics[0].source_count == 2


def test_unknown_evidence_reference_is_rejected() -> None:
    first_id, second_id = uuid4(), uuid4()
    pack = ActionPack.model_validate(_pack_payload(first_id, second_id))
    sources = [
        SourceDocument(
            id=first_id,
            title="arrays.md",
            source_kind="file",
            source_type="text/markdown",
            content="Arrays",
            estimated_minutes=1,
            available_locations=frozenset(),
        ),
        SourceDocument(
            id=uuid4(),
            title="graphs.md",
            source_kind="file",
            source_type="text/markdown",
            content="Graphs",
            estimated_minutes=1,
            available_locations=frozenset(),
        ),
    ]

    with pytest.raises(InfrastructureError) as error:
        validate_action_pack(
            pack,
            sources,
            repeated_percentage=0,
            estimated_minutes=2,
        )

    assert error.value.code == "gemini_invalid_evidence"
