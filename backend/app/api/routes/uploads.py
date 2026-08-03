"""Validated source-upload endpoint."""

from fastapi import APIRouter, File, Request, UploadFile, status

from app.models.upload import UploadMetadata, UploadResponse
from app.services.file_validation import validate_upload

router = APIRouter(prefix="/api/v1", tags=["uploads"])


@router.post(
    "/uploads",
    response_model=UploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Validate and store one learning resource",
)
async def create_upload(
    request: Request,
    file: UploadFile = File(...),
) -> UploadResponse:
    settings = request.app.state.settings
    try:
        validated = await validate_upload(
            file,
            max_size_bytes=settings.max_upload_size_bytes,
        )
    finally:
        await file.close()

    record = await request.app.state.upload_service.store(validated)
    return UploadResponse(upload=UploadMetadata.from_record(record))
