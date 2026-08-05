"""Deterministic, bounded text extraction for uploaded learning resources."""

from __future__ import annotations

import io
import re
import warnings
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from PIL import Image, ImageFilter, ImageStat
from pypdf import PdfReader

from app.services.file_validation import (
    MAX_ZIP_ENTRIES,
    MAX_ZIP_COMPRESSION_RATIO,
    MAX_ZIP_UNCOMPRESSED_BYTES,
)

TEXT_EXTENSIONS = {".txt", ".md", ".srt", ".vtt"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
SUPPORTED_ARCHIVE_EXTENSIONS = TEXT_EXTENSIONS | IMAGE_EXTENSIONS | {".pdf"}
TIMESTAMP_LINE = re.compile(
    r"^\s*(?:\d{1,2}:)?\d{2}:\d{2}[,.]\d{3}\s+-->\s+"
    r"(?:\d{1,2}:)?\d{2}:\d{2}[,.]\d{3}"
)
HTML_TAG = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class ExtractionResult:
    text: str
    outcome: str
    technical_reason: str
    confidence: float | None
    extracted_pages: int | None = None
    total_pages: int | None = None
    detected_language: str | None = None
    archive_entries_processed: int | None = None
    archive_entries_total: int | None = None

    @property
    def character_count(self) -> int:
        return len(self.text)


def extract_resource(filename: str, data: bytes) -> ExtractionResult:
    """Extract one already-validated source without network or model calls."""
    extension = Path(filename).suffix.lower()
    if extension in TEXT_EXTENSIONS:
        return _extract_text(data, subtitle=extension in {".srt", ".vtt"})
    if extension == ".pdf":
        return _extract_pdf(data)
    if extension in IMAGE_EXTENSIONS:
        return _extract_image(data)
    if extension == ".zip":
        return _extract_zip(data)
    return ExtractionResult(
        text="",
        outcome="unsupported",
        technical_reason=f"No extractor is registered for {extension or 'this format'}.",
        confidence=None,
    )


def _extract_text(data: bytes, *, subtitle: bool) -> ExtractionResult:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return ExtractionResult(
            text="",
            outcome="unreadable",
            technical_reason="The text is not valid UTF-8.",
            confidence=0.0,
        )

    if subtitle:
        lines = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if (
                not line
                or line.isdigit()
                or line.upper() == "WEBVTT"
                or line.startswith(("NOTE", "STYLE", "REGION"))
                or TIMESTAMP_LINE.match(line)
            ):
                continue
            cleaned = HTML_TAG.sub("", line).strip()
            if cleaned:
                lines.append(cleaned)
        text = "\n".join(lines)

    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return ExtractionResult(
            text="",
            outcome="unreadable",
            technical_reason="The file contains no extractable text.",
            confidence=0.0,
        )
    return ExtractionResult(
        text=text,
        outcome="ready",
        technical_reason="UTF-8 text was extracted successfully.",
        confidence=1.0,
        detected_language=detect_language(text),
    )


def _extract_pdf(data: bytes) -> ExtractionResult:
    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
    except Exception:
        return ExtractionResult(
            text="",
            outcome="unreadable",
            technical_reason="The PDF structure could not be read.",
            confidence=0.0,
        )

    if reader.is_encrypted:
        return ExtractionResult(
            text="",
            outcome="unsupported",
            technical_reason="The PDF is encrypted.",
            confidence=None,
            extracted_pages=0,
            total_pages=len(reader.pages),
        )

    page_text: list[str] = []
    failed_pages = 0
    total_pages = len(reader.pages)
    for page in reader.pages:
        try:
            extracted = (page.extract_text() or "").strip()
        except Exception:
            extracted = ""
        if extracted:
            page_text.append(extracted)
        else:
            failed_pages += 1

    text = "\n\n".join(page_text)
    extracted_pages = total_pages - failed_pages
    if not text:
        return ExtractionResult(
            text="",
            outcome="unreadable",
            technical_reason=(
                "No embedded text was found; this may be a scanned or blank PDF."
            ),
            confidence=0.0,
            extracted_pages=0,
            total_pages=total_pages,
        )
    if failed_pages:
        return ExtractionResult(
            text=text,
            outcome="partial",
            technical_reason=(
                f"{failed_pages} of {total_pages} PDF pages had no readable text."
            ),
            confidence=round(extracted_pages / max(total_pages, 1), 3),
            extracted_pages=extracted_pages,
            total_pages=total_pages,
            detected_language=detect_language(text),
        )
    return ExtractionResult(
        text=text,
        outcome="ready",
        technical_reason="Embedded text was extracted from every PDF page.",
        confidence=0.98,
        extracted_pages=total_pages,
        total_pages=total_pages,
        detected_language=detect_language(text),
    )


def _extract_image(data: bytes) -> ExtractionResult:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                image.load()
                width, height = image.size
                gray = image.convert("L")
                contrast = ImageStat.Stat(gray).stddev[0]
                edges = gray.filter(ImageFilter.FIND_EDGES)
                edge_variance = ImageStat.Stat(edges).var[0]
    except Exception:
        return ExtractionResult(
            text="",
            outcome="unreadable",
            technical_reason="The image could not be decoded.",
            confidence=0.0,
        )

    if width < 320 or height < 180:
        return ExtractionResult(
            text="",
            outcome="unreadable",
            technical_reason=(
                f"The image is too small for dependable text extraction "
                f"({width}x{height}px)."
            ),
            confidence=0.1,
        )
    if contrast < 8:
        return ExtractionResult(
            text="",
            outcome="unreadable",
            technical_reason="The image has too little contrast to read.",
            confidence=0.1,
        )
    if edge_variance < 45:
        return ExtractionResult(
            text="",
            outcome="low_confidence",
            technical_reason="The image appears blurred, so code text may be inaccurate.",
            confidence=0.35,
        )

    # OCR is intentionally optional: production hosts may expose pytesseract,
    # while local low-RAM development remains dependency-free.
    try:
        import pytesseract  # type: ignore[import-not-found]

        with Image.open(io.BytesIO(data)) as image:
            text = pytesseract.image_to_string(image).strip()
    except Exception:
        text = ""

    if len(text) < 20:
        return ExtractionResult(
            text=text,
            outcome="low_confidence",
            technical_reason=(
                "The image passed quality checks, but OCR produced insufficient text."
            ),
            confidence=0.4,
            detected_language=detect_language(text) if text else None,
        )
    return ExtractionResult(
        text=text,
        outcome="ready",
        technical_reason="Image text was extracted with local OCR.",
        confidence=0.78,
        detected_language=detect_language(text),
    )


def _extract_zip(data: bytes) -> ExtractionResult:
    extracted_sections: list[str] = []
    processed = 0
    failed = 0

    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except (OSError, zipfile.BadZipFile):
        return ExtractionResult(
            text="",
            outcome="unreadable",
            technical_reason="The ZIP archive could not be opened.",
            confidence=0.0,
        )

    with archive:
        entries = [entry for entry in archive.infolist() if not entry.is_dir()]
        if len(entries) > MAX_ZIP_ENTRIES:
            return ExtractionResult(
                text="",
                outcome="unsupported",
                technical_reason="The ZIP contains too many entries.",
                confidence=None,
                archive_entries_total=len(entries),
            )

        if sum(entry.file_size for entry in entries) > MAX_ZIP_UNCOMPRESSED_BYTES:
            return ExtractionResult(
                text="",
                outcome="unsupported",
                technical_reason="The ZIP expands beyond the safe processing limit.",
                confidence=None,
                archive_entries_total=len(entries),
            )

        for entry in entries:
            path = PurePosixPath(entry.filename.replace("\\", "/"))
            if (
                path.is_absolute()
                or ".." in path.parts
                or entry.flag_bits & 0x1
                or (
                    entry.compress_size
                    and entry.file_size / entry.compress_size
                    > MAX_ZIP_COMPRESSION_RATIO
                )
            ):
                failed += 1
                continue
            extension = Path(entry.filename).suffix.lower()
            if extension not in SUPPORTED_ARCHIVE_EXTENSIONS:
                failed += 1
                continue
            try:
                entry_data = archive.read(entry)
                result = extract_resource(entry.filename, entry_data)
            except (OSError, RuntimeError, zipfile.BadZipFile):
                failed += 1
                continue
            if result.text:
                processed += 1
                extracted_sections.append(
                    f"--- {Path(entry.filename).name} ---\n{result.text}"
                )
            else:
                failed += 1

    text = "\n\n".join(extracted_sections)
    total = len(entries)
    if not text:
        return ExtractionResult(
            text="",
            outcome="unsupported" if failed else "unreadable",
            technical_reason="No supported, readable resources were found in the ZIP.",
            confidence=0.0,
            archive_entries_processed=0,
            archive_entries_total=total,
        )
    outcome = "partial" if failed else "ready"
    reason = (
        f"Extracted {processed} of {total} ZIP entries; "
        f"{failed} entries were unsupported or unreadable."
        if failed
        else f"Extracted all {processed} supported ZIP entries."
    )
    return ExtractionResult(
        text=text,
        outcome=outcome,
        technical_reason=reason,
        confidence=round(processed / max(total, 1), 3),
        detected_language=detect_language(text),
        archive_entries_processed=processed,
        archive_entries_total=total,
    )


def detect_language(text: str) -> str:
    """Return a deliberately conservative language hint."""
    letters = [character for character in text if character.isalpha()]
    if not letters:
        return "unknown"
    ascii_ratio = sum(character.isascii() for character in letters) / len(letters)
    return "en" if ascii_ratio >= 0.9 else "unknown"
