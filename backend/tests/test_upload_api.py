"""Upload endpoint orchestration test with isolated infrastructure."""

from datetime import UTC, datetime
from uuid import uuid4

from fastapi.testclient import TestClient

from app.integrations.database import UploadRecord
from app.main import app


class FakeUploadService:
    async def store(self, upload) -> UploadRecord:
        return UploadRecord(
            id=uuid4(),
            original_filename=upload.original_filename,
            object_key=f"uploads/test/{upload.sha256}.txt",
            content_type=upload.content_type,
            size_bytes=upload.size_bytes,
            sha256=upload.sha256,
            status="stored",
            b2_bucket="test-bucket",
            created_at=datetime.now(UTC),
        )

    def close(self) -> None:
        return None


def test_upload_endpoint_returns_stored_metadata() -> None:
    original_service = app.state.upload_service
    app.state.upload_service = FakeUploadService()
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/uploads",
                files={"file": ("notes.txt", b"hello backlog", "text/plain")},
            )
    finally:
        app.state.upload_service = original_service

    assert response.status_code == 201
    payload = response.json()["upload"]
    assert payload["filename"] == "notes.txt"
    assert payload["status"] == "stored"
    assert payload["bucket"] == "test-bucket"
    assert len(payload["sha256"]) == 64
