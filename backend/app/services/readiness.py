"""Deterministic relevance, similarity, and readiness decisions."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from uuid import UUID

from app.services.extraction import ExtractionResult

TOKEN_PATTERN = re.compile(r"[a-zA-Z][a-zA-Z0-9+#.-]*")
WHITESPACE = re.compile(r"\s+")
CODING_SIGNALS = {
    "algorithm",
    "algorithms",
    "array",
    "arrays",
    "binary search",
    "coding interview",
    "complexity",
    "data structure",
    "data structures",
    "dynamic programming",
    "graph",
    "graphs",
    "hash map",
    "heap",
    "interview preparation",
    "leetcode",
    "linked list",
    "linked lists",
    "queue",
    "queues",
    "recursion",
    "searching",
    "sorting",
    "stack",
    "stacks",
    "string",
    "strings",
    "system design",
    "tree",
    "trees",
}
LANGUAGE_SIGNALS = {
    "c++",
    "golang",
    "java",
    "javascript",
    "kotlin",
    "python",
    "rust",
    "typescript",
}
STRUCTURAL_SIGNALS = (
    re.compile(r"\b(?:def|class|function|interface|public static|return)\b"),
    re.compile(r"\bO\([^)]+\)"),
    re.compile(r"(?:=>|==|!=|<=|>=|\+\+|--|::)"),
    re.compile(r"[{};]\s*$", re.MULTILINE),
)


@dataclass(frozen=True)
class DuplicateMatch:
    resource_id: UUID
    filename: str
    kind: str
    similarity: float


@dataclass(frozen=True)
class ReadinessDecision:
    status: str
    explanation: str
    technical_reason: str
    confidence: float | None
    suggested_action: str
    content_summary: str | None
    signature: tuple[str, ...]
    duplicate: DuplicateMatch | None = None


def build_signature(text: str) -> tuple[str, ...]:
    """Create a compact, stable signature of normalized three-token shingles."""
    tokens = [token.lower() for token in TOKEN_PATTERN.findall(text)]
    if not tokens:
        return ()
    width = min(3, len(tokens))
    shingles = {
        " ".join(tokens[index : index + width])
        for index in range(len(tokens) - width + 1)
    }
    hashes = {
        hashlib.sha1(shingle.encode("utf-8")).hexdigest()[:12]
        for shingle in shingles
    }
    return tuple(sorted(hashes)[:512])


def similarity_score(
    left_signature: tuple[str, ...],
    right_signature: tuple[str, ...],
) -> float:
    left = set(left_signature)
    right = set(right_signature)
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def is_coding_relevant(text: str) -> tuple[bool, str]:
    normalized = WHITESPACE.sub(" ", text.lower())
    matched = sorted(
        signal
        for signal in CODING_SIGNALS | LANGUAGE_SIGNALS
        if signal in normalized
    )
    structural_count = sum(bool(pattern.search(text)) for pattern in STRUCTURAL_SIGNALS)
    if matched or structural_count >= 2:
        evidence = ", ".join(matched[:4])
        reason = (
            f"Detected coding-preparation signals: {evidence}."
            if evidence
            else "Detected multiple source-code structures."
        )
        return True, reason
    return (
        False,
        "No meaningful coding, DSA, interview-preparation, or code-structure "
        "signals were detected.",
    )


def decide_readiness(
    extraction: ExtractionResult | None,
    *,
    exact_duplicate: DuplicateMatch | None = None,
    near_duplicate: DuplicateMatch | None = None,
) -> ReadinessDecision:
    """Apply transparent precedence to produce exactly one primary status."""
    if exact_duplicate is not None:
        return ReadinessDecision(
            status="duplicate",
            explanation=(
                f"Duplicate — this exactly matches {exact_duplicate.filename}."
            ),
            technical_reason="The source files have identical SHA-256 fingerprints.",
            confidence=1.0,
            suggested_action="Remove it or choose Include Anyway to keep both.",
            content_summary=None,
            signature=(),
            duplicate=exact_duplicate,
        )

    if extraction is None:
        return ReadinessDecision(
            status="failed",
            explanation="Failed — extraction could not be completed.",
            technical_reason="The extraction pipeline returned no result.",
            confidence=None,
            suggested_action="Retry processing or replace this resource.",
            content_summary=None,
            signature=(),
        )

    signature = build_signature(extraction.text)
    summary = summarize_text(extraction.text)

    if extraction.outcome == "unsupported":
        return ReadinessDecision(
            status="unsupported",
            explanation="Unsupported — this file cannot be processed safely.",
            technical_reason=extraction.technical_reason,
            confidence=extraction.confidence,
            suggested_action="Replace it with a supported, unencrypted resource.",
            content_summary=summary,
            signature=signature,
        )
    if extraction.outcome == "unreadable":
        return ReadinessDecision(
            status="unreadable",
            explanation="Unreadable — no dependable text could be extracted.",
            technical_reason=extraction.technical_reason,
            confidence=extraction.confidence,
            suggested_action="Replace it with a clearer or text-based version.",
            content_summary=summary,
            signature=signature,
        )
    if extraction.outcome == "low_confidence":
        return ReadinessDecision(
            status="low_confidence",
            explanation=(
                "Low confidence — the resource may contain inaccurate or "
                "insufficient extracted text."
            ),
            technical_reason=extraction.technical_reason,
            confidence=extraction.confidence,
            suggested_action="Review the details, retry, or upload a clearer copy.",
            content_summary=summary,
            signature=signature,
        )

    if near_duplicate is not None:
        percentage = round(near_duplicate.similarity * 100)
        return ReadinessDecision(
            status="duplicate",
            explanation=(
                f"Duplicate — this is {percentage}% similar to "
                f"{near_duplicate.filename}."
            ),
            technical_reason=(
                "Normalized three-token shingles crossed the near-duplicate "
                "similarity threshold."
            ),
            confidence=near_duplicate.similarity,
            suggested_action="Remove it or choose Include Anyway to keep both.",
            content_summary=summary,
            signature=signature,
            duplicate=near_duplicate,
        )

    relevant, relevance_reason = is_coding_relevant(extraction.text)
    if not relevant:
        return ReadinessDecision(
            status="irrelevant",
            explanation=(
                "Irrelevant — this appears unrelated to coding or DSA preparation."
            ),
            technical_reason=relevance_reason,
            confidence=0.82,
            suggested_action="Remove it, replace it, or choose Include Anyway.",
            content_summary=summary,
            signature=signature,
        )

    if extraction.outcome == "partial":
        if extraction.total_pages is not None:
            detail = (
                f"{extraction.extracted_pages} of "
                f"{extraction.total_pages} pages were extracted."
            )
        else:
            detail = extraction.technical_reason
        return ReadinessDecision(
            status="partial",
            explanation=f"Partial — {detail}",
            technical_reason=extraction.technical_reason,
            confidence=extraction.confidence,
            suggested_action="Review the missing content or upload a clearer copy.",
            content_summary=summary,
            signature=signature,
        )

    if extraction.total_pages is not None:
        explanation = (
            f"Ready — {extraction.extracted_pages} pages extracted successfully."
        )
    else:
        explanation = (
            f"Ready — {extraction.character_count:,} characters extracted "
            "successfully."
        )
    return ReadinessDecision(
        status="ready",
        explanation=explanation,
        technical_reason=(
            f"{extraction.technical_reason} {relevance_reason}"
        ),
        confidence=extraction.confidence,
        suggested_action="No action is needed.",
        content_summary=summary,
        signature=signature,
    )


def summarize_text(text: str, limit: int = 220) -> str | None:
    normalized = WHITESPACE.sub(" ", text).strip()
    if not normalized:
        return None
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "…"
