"""Focused upload-validation tests."""

import asyncio
import io

import pytest
from fastapi import UploadFile

from app.services.errors import UploadValidationError
from app.services.file_validation import validate_upload


def test_valid_utf8_text_file() -> None:
    upload = UploadFile(
        filename="notes.txt",
        file=io.BytesIO(b"dynamic programming notes"),
    )

    validated = asyncio.run(validate_upload(upload, max_size_bytes=1024))

    assert validated.content_type == "text/plain"
    assert validated.size_bytes == 25
    assert len(validated.sha256) == 64


def test_rejects_unsupported_extension() -> None:
    upload = UploadFile(filename="video.mp4", file=io.BytesIO(b"not a video"))

    with pytest.raises(UploadValidationError) as error:
        asyncio.run(validate_upload(upload, max_size_bytes=1024))

    assert error.value.code == "unsupported_file_type"


def test_rejects_file_over_size_limit() -> None:
    upload = UploadFile(filename="large.txt", file=io.BytesIO(b"x" * 20))

    with pytest.raises(UploadValidationError) as error:
        asyncio.run(validate_upload(upload, max_size_bytes=10))

    assert error.value.code == "file_too_large"


def test_rejects_corrupt_image() -> None:
    upload = UploadFile(filename="broken.png", file=io.BytesIO(b"not-png"))

    with pytest.raises(UploadValidationError) as error:
        asyncio.run(validate_upload(upload, max_size_bytes=1024))

    assert error.value.code == "corrupt_file"
