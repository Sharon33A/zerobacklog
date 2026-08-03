"""Bounded validation for supported upload formats."""

from __future__ import annotations

import hashlib
import io
import warnings
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from fastapi import UploadFile
from PIL import Image
from pypdf import PdfReader

from app.services.errors import UploadValidationError

READ_CHUNK_SIZE = 1024 * 1024
MAX_ZIP_ENTRIES = 1_000
MAX_ZIP_UNCOMPRESSED_BYTES = 250 * 1024 * 1024
MAX_ZIP_COMPRESSION_RATIO = 100

SUPPORTED_TYPES = {
    ".pdf": ("application/pdf", "pdf"),
    ".png": ("image/png", "image"),
    ".jpg": ("image/jpeg", "image"),
    ".jpeg": ("image/jpeg", "image"),
    ".webp": ("image/webp", "image"),
    ".gif": ("image/gif", "image"),
    ".txt": ("text/plain", "text"),
    ".md": ("text/markdown", "text"),
    ".csv": ("text/csv", "text"),
    ".json": ("application/json", "text"),
    ".zip": ("application/zip", "zip"),
}

IMAGE_FORMATS = {
    ".png": "PNG",
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".webp": "WEBP",
    ".gif": "GIF",
}


@dataclass(frozen=True)
class ValidatedUpload:
    original_filename: str
    extension: str
    content_type: str
    size_bytes: int
    sha256: str
    data: bytes


async def validate_upload(
    upload: UploadFile,
    *,
    max_size_bytes: int,
) -> ValidatedUpload:
    original_filename = Path(upload.filename or "").name.strip()
    if not original_filename:
        raise UploadValidationError(
            "missing_filename",
            "The uploaded file must have a filename.",
        )

    extension = Path(original_filename).suffix.lower()
    type_definition = SUPPORTED_TYPES.get(extension)
    if type_definition is None:
        raise UploadValidationError(
            "unsupported_file_type",
            "Supported files are PDF, image, text, and ZIP formats.",
        )

    content_type, category = type_definition
    body = bytearray()
    digest = hashlib.sha256()

    while chunk := await upload.read(READ_CHUNK_SIZE):
        body.extend(chunk)
        digest.update(chunk)
        if len(body) > max_size_bytes:
            raise UploadValidationError(
                "file_too_large",
                f"Files must be {max_size_bytes // (1024 * 1024)} MB or smaller.",
            )

    data = bytes(body)
    if not data:
        raise UploadValidationError("empty_file", "Empty files cannot be uploaded.")

    try:
        if category == "pdf":
            _validate_pdf(data)
        elif category == "image":
            _validate_image(data, extension)
        elif category == "text":
            _validate_text(data)
        elif category == "zip":
            _validate_zip(data)
    except UploadValidationError:
        raise
    except Exception as exception:
        raise UploadValidationError(
            "corrupt_file",
            "The file appears to be corrupt or unreadable.",
        ) from exception

    return ValidatedUpload(
        original_filename=original_filename,
        extension=extension,
        content_type=content_type,
        size_bytes=len(data),
        sha256=digest.hexdigest(),
        data=data,
    )


def _validate_pdf(data: bytes) -> None:
    if not data.startswith(b"%PDF-"):
        raise UploadValidationError("invalid_pdf", "The PDF signature is invalid.")
    reader = PdfReader(io.BytesIO(data), strict=False)
    if reader.is_encrypted:
        raise UploadValidationError(
            "encrypted_pdf",
            "Encrypted PDFs are not supported.",
        )
    if not reader.pages:
        raise UploadValidationError("invalid_pdf", "The PDF contains no pages.")


def _validate_image(data: bytes, extension: str) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(data)) as image:
            if image.format != IMAGE_FORMATS[extension]:
                raise UploadValidationError(
                    "image_type_mismatch",
                    "The image contents do not match its extension.",
                )
            image.verify()


def _validate_text(data: bytes) -> None:
    text = data.decode("utf-8-sig")
    if "\x00" in text:
        raise UploadValidationError(
            "invalid_text",
            "Text files cannot contain binary null bytes.",
        )


def _validate_zip(data: bytes) -> None:
    buffer = io.BytesIO(data)
    if not zipfile.is_zipfile(buffer):
        raise UploadValidationError("invalid_zip", "The ZIP signature is invalid.")

    buffer.seek(0)
    with zipfile.ZipFile(buffer) as archive:
        entries = archive.infolist()
        if len(entries) > MAX_ZIP_ENTRIES:
            raise UploadValidationError(
                "zip_too_many_entries",
                "The ZIP contains too many entries.",
            )

        total_uncompressed = 0
        for entry in entries:
            path = PurePosixPath(entry.filename.replace("\\", "/"))
            if path.is_absolute() or ".." in path.parts:
                raise UploadValidationError(
                    "unsafe_zip_path",
                    "The ZIP contains an unsafe path.",
                )
            if entry.flag_bits & 0x1:
                raise UploadValidationError(
                    "encrypted_zip",
                    "Encrypted ZIP files are not supported.",
                )
            total_uncompressed += entry.file_size
            if total_uncompressed > MAX_ZIP_UNCOMPRESSED_BYTES:
                raise UploadValidationError(
                    "zip_expands_too_large",
                    "The ZIP expands beyond the supported limit.",
                )
            if entry.file_size and entry.compress_size == 0:
                raise UploadValidationError(
                    "unsafe_zip_ratio",
                    "The ZIP has an unsafe compression ratio.",
                )
            if (
                entry.compress_size
                and entry.file_size / entry.compress_size
                > MAX_ZIP_COMPRESSION_RATIO
            ):
                raise UploadValidationError(
                    "unsafe_zip_ratio",
                    "The ZIP has an unsafe compression ratio.",
                )

        corrupt_entry = archive.testzip()
        if corrupt_entry is not None:
            raise UploadValidationError(
                "corrupt_zip",
                "The ZIP contains a corrupt entry.",
            )
