"""Public-link intake and readiness endpoints."""

from uuid import UUID

from fastapi import APIRouter, Request, status

from app.models.link import LinkCreateRequest, LinkReadiness, LinkResponse

router = APIRouter(prefix="/api/v1", tags=["links"])


def _response(record) -> LinkResponse:
    return LinkResponse(link=LinkReadiness.from_record(record))


@router.post(
    "/links",
    response_model=LinkResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Validate, retrieve, and store one public learning link",
)
async def create_link(
    body: LinkCreateRequest,
    request: Request,
) -> LinkResponse:
    record = await request.app.state.link_service.create(
        body.project_id,
        str(body.url),
    )
    return _response(record)


@router.post(
    "/links/{link_id}/process",
    response_model=LinkResponse,
    summary="Retry public-link retrieval",
)
async def process_link(link_id: UUID, request: Request) -> LinkResponse:
    return _response(await request.app.state.link_service.process(link_id))


@router.get(
    "/links/{link_id}",
    response_model=LinkResponse,
    summary="Retrieve public-link readiness",
)
async def get_link(link_id: UUID, request: Request) -> LinkResponse:
    return _response(await request.app.state.link_service.get(link_id))


@router.post(
    "/links/{link_id}/approve",
    response_model=LinkResponse,
    summary="Include a partial or irrelevant link anyway",
)
async def approve_link(link_id: UUID, request: Request) -> LinkResponse:
    return _response(await request.app.state.link_service.approve(link_id))


@router.delete(
    "/links/{link_id}",
    response_model=LinkResponse,
    summary="Remove a public link from the project",
)
async def remove_link(link_id: UUID, request: Request) -> LinkResponse:
    return _response(await request.app.state.link_service.remove(link_id))
