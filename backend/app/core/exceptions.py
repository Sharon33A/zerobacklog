"""Centralized HTTP exception responses."""

import logging

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.models.error import ErrorDetail, ErrorResponse
from app.services.errors import (
    DuplicateUploadError,
    InfrastructureError,
    UploadValidationError,
)

logger = logging.getLogger(__name__)


def _error_response(
    *,
    status_code: int,
    code: str,
    message: str,
) -> JSONResponse:
    body = ErrorResponse(error=ErrorDetail(code=code, message=message))
    return JSONResponse(status_code=status_code, content=body.model_dump())


async def http_exception_handler(
    request: Request, exception: Exception
) -> JSONResponse:
    """Normalize framework HTTP errors without exposing internal objects."""
    if not isinstance(exception, HTTPException):
        raise exception

    message = (
        exception.detail
        if isinstance(exception.detail, str)
        else "The request could not be completed."
    )
    logger.warning(
        "HTTP error status=%s method=%s path=%s",
        exception.status_code,
        request.method,
        request.url.path,
    )
    return _error_response(
        status_code=exception.status_code,
        code="http_error",
        message=message,
    )


async def validation_exception_handler(
    request: Request, exception: Exception
) -> JSONResponse:
    """Return a stable validation error without echoing submitted values."""
    error_count = (
        len(exception.errors())
        if isinstance(exception, RequestValidationError)
        else 0
    )
    logger.warning(
        "Request validation failed method=%s path=%s error_count=%s",
        request.method,
        request.url.path,
        error_count,
    )
    return _error_response(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        code="request_validation_error",
        message="The request contains invalid or missing data.",
    )


async def unexpected_exception_handler(
    request: Request, exception: Exception
) -> JSONResponse:
    """Log unexpected errors server-side and return a safe public response."""
    logger.exception(
        "Unhandled application error method=%s path=%s",
        request.method,
        request.url.path,
        exc_info=exception,
    )
    return _error_response(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        code="internal_server_error",
        message="An unexpected error occurred.",
    )


async def upload_validation_exception_handler(
    request: Request, exception: Exception
) -> JSONResponse:
    if not isinstance(exception, UploadValidationError):
        raise exception
    logger.info(
        "Upload rejected code=%s path=%s",
        exception.code,
        request.url.path,
    )
    return _error_response(
        status_code=status.HTTP_400_BAD_REQUEST,
        code=exception.code,
        message=exception.message,
    )


async def duplicate_upload_exception_handler(
    request: Request, exception: Exception
) -> JSONResponse:
    if not isinstance(exception, DuplicateUploadError):
        raise exception
    message = "This file has already been uploaded."
    if exception.existing_upload_id:
        message += f" Existing upload ID: {exception.existing_upload_id}."
    return _error_response(
        status_code=status.HTTP_409_CONFLICT,
        code="duplicate_upload",
        message=message,
    )


async def infrastructure_exception_handler(
    request: Request, exception: Exception
) -> JSONResponse:
    if not isinstance(exception, InfrastructureError):
        raise exception
    logger.error(
        "Infrastructure operation failed code=%s path=%s",
        exception.code,
        request.url.path,
    )
    return _error_response(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        code=exception.code,
        message=exception.message,
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Register every application-wide exception mapping."""
    app.add_exception_handler(
        UploadValidationError,
        upload_validation_exception_handler,
    )
    app.add_exception_handler(
        DuplicateUploadError,
        duplicate_upload_exception_handler,
    )
    app.add_exception_handler(
        InfrastructureError,
        infrastructure_exception_handler,
    )
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unexpected_exception_handler)
