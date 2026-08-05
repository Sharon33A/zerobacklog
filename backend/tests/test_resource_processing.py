"""Focused extraction, readiness, duplicate, and action tests."""

from __future__ import annotations

import io
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

from fastapi.testclient import TestClient
from PIL import Image
from pypdf import PdfWriter
from pypdf.generic import (
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
)

import app.services.extraction as extraction_module
from app.integrations.database import ResourceRecord
from app.main import app
from app.services.extraction import ExtractionResult, extract_resource
from app.services.readiness import (
    DuplicateMatch,
    build_signature,
    decide_readiness,
    similarity_score,
)


def _text_pdf(text: str) -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    font_reference = writer._add_object(font)
    page[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/Font"): DictionaryObject(
                {NameObject("/F1"): font_reference}
            )
        }
    )
    stream = DecodedStreamObject()
    safe_text = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream.set_data(f"BT /F1 12 Tf 72 720 Td ({safe_text}) Tj ET".encode())
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def test_valid_text_extraction() -> None:
    result = extract_resource(
        "arrays.md",
        b"# Arrays\nUse binary search for sorted arrays.",
    )

    assert result.outcome == "ready"
    assert "binary search" in result.text
    assert result.detected_language == "en"


def test_valid_pdf_extraction() -> None:
    result = extract_resource(
        "interview.pdf",
        _text_pdf("Dynamic programming and recursion interview notes"),
    )

    assert result.outcome == "ready"
    assert result.extracted_pages == 1
    assert "Dynamic programming" in result.text


def test_unreadable_image_is_reported() -> None:
    output = io.BytesIO()
    Image.new("RGB", (80, 60), "white").save(output, format="PNG")

    result = extract_resource("tiny.png", output.getvalue())

    assert result.outcome == "unreadable"
    assert "too small" in result.technical_reason


def test_irrelevant_content_is_explained() -> None:
    extraction = ExtractionResult(
        text="A sourdough recipe with flour, water, salt, and baking times.",
        outcome="ready",
        technical_reason="Text extracted.",
        confidence=1.0,
        detected_language="en",
    )

    decision = decide_readiness(extraction)

    assert decision.status == "irrelevant"
    assert "unrelated to coding" in decision.explanation


def test_exact_duplicate_identifies_original() -> None:
    original_id = uuid4()
    decision = decide_readiness(
        None,
        exact_duplicate=DuplicateMatch(
            resource_id=original_id,
            filename="Arrays Notes.pdf",
            kind="exact",
            similarity=1.0,
        ),
    )

    assert decision.status == "duplicate"
    assert decision.duplicate
    assert decision.duplicate.resource_id == original_id
    assert "SHA-256" in decision.technical_reason


def test_near_duplicate_similarity() -> None:
    original = (
        "Arrays support indexed access. Binary search finds a target in sorted "
        "arrays with logarithmic time complexity. Two pointers solve many "
        "coding interview problems efficiently."
    )
    revision = original + " Practice this pattern before interviews."
    score = similarity_score(build_signature(original), build_signature(revision))

    decision = decide_readiness(
        ExtractionResult(
            text=revision,
            outcome="ready",
            technical_reason="Text extracted.",
            confidence=1.0,
        ),
        near_duplicate=DuplicateMatch(
            resource_id=uuid4(),
            filename="arrays-original.md",
            kind="near",
            similarity=score,
        ),
    )

    assert score >= 0.80
    assert decision.status == "duplicate"
    assert decision.duplicate and decision.duplicate.kind == "near"


def test_partial_pdf_extraction(monkeypatch) -> None:
    class FakePage:
        def __init__(self, text: str) -> None:
            self.text = text

        def extract_text(self) -> str:
            return self.text

    class FakeReader:
        is_encrypted = False
        pages = [
            FakePage("Graphs and breadth first search"),
            FakePage(""),
        ]

    monkeypatch.setattr(
        extraction_module,
        "PdfReader",
        lambda *_args, **_kwargs: FakeReader(),
    )

    result = extraction_module._extract_pdf(b"%PDF-test")
    decision = decide_readiness(result)

    assert result.outcome == "partial"
    assert result.extracted_pages == 1
    assert decision.status == "partial"


def _resource_record(*, status: str = "irrelevant") -> ResourceRecord:
    now = datetime.now(UTC)
    return ResourceRecord(
        id=uuid4(),
        project_id=uuid4(),
        filename="weekend-plans.txt",
        content_type="text/plain",
        size_bytes=100,
        sha256="a" * 64,
        source_object_key="uploads/test/source.txt",
        lifecycle_state=status,
        readiness_status=status,
        explanation="Needs a decision.",
        technical_reason="No coding signals.",
        confidence=0.82,
        extracted_character_count=100,
        extracted_page_count=None,
        total_page_count=None,
        detected_language="en",
        duplicate_match_id=None,
        duplicate_match_filename=None,
        duplicate_kind=None,
        duplicate_similarity=None,
        suggested_action="Remove or include.",
        content_summary="Weekend plans.",
        extracted_object_key="derived/test/extracted.txt",
        metadata_object_key="derived/test/readiness.json",
        similarity_signature=("abc",),
        approved=False,
        replacement_requested=False,
        removed=False,
        created_at=now,
        updated_at=now,
    )


class FakeResourceService:
    def __init__(self) -> None:
        self.record = _resource_record()

    async def approve(self, resource_id):
        assert resource_id == self.record.id
        self.record = replace(
            self.record,
            approved=True,
            lifecycle_state="ready_for_analysis",
        )
        return self.record

    async def remove(self, resource_id):
        assert resource_id == self.record.id
        self.record = replace(
            self.record,
            removed=True,
            lifecycle_state="removed",
        )
        return self.record

    def close(self) -> None:
        return None


def test_remove_and_override_actions() -> None:
    original_service = app.state.resource_service
    fake_service = FakeResourceService()
    app.state.resource_service = fake_service
    try:
        with TestClient(app) as client:
            approval = client.post(
                f"/api/v1/resources/{fake_service.record.id}/approve"
            )
            removal = client.delete(
                f"/api/v1/resources/{fake_service.record.id}"
            )
    finally:
        app.state.resource_service = original_service

    assert approval.status_code == 200
    assert approval.json()["resource"]["approved"] is True
    assert approval.json()["resource"]["eligible_for_analysis"] is True
    assert removal.status_code == 200
    assert removal.json()["resource"]["removed"] is True
