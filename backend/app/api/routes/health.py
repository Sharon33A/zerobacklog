"""Health-check routes."""

from fastapi import APIRouter, Request, status

from app.models.health import HealthResponse

router = APIRouter(tags=["health"])


def _health_response(request: Request) -> HealthResponse:
    settings = request.app.state.settings
    return HealthResponse(
        service=settings.service_name,
        status="ok",
        version=settings.app_version,
        environment=settings.app_env,
    )


@router.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Check service health",
)
async def health(request: Request) -> HealthResponse:
    """Return public operational metadata for the service."""
    return _health_response(request)


@router.get(
    "/api/v1/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Check versioned API health",
)
async def versioned_health(request: Request) -> HealthResponse:
    """Return public operational metadata through the versioned API."""
    return _health_response(request)
