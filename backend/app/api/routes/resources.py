"""Resource extraction, readiness, and user-decision endpoints."""

from uuid import UUID

from fastapi import APIRouter, Request

from app.models.resource import (
    ResourceListResponse,
    ResourceReadiness,
    ResourceResponse,
)

router = APIRouter(prefix="/api/v1", tags=["resources"])


def _response(record) -> ResourceResponse:
    return ResourceResponse(resource=ResourceReadiness.from_record(record))


@router.post(
    "/resources/{resource_id}/process",
    response_model=ResourceResponse,
    summary="Validate, extract, and classify one resource",
)
async def process_resource(
    resource_id: UUID,
    request: Request,
) -> ResourceResponse:
    record = await request.app.state.resource_service.process(resource_id)
    return _response(record)


@router.get(
    "/resources/{resource_id}/readiness",
    response_model=ResourceResponse,
    summary="Retrieve one resource readiness result",
)
async def get_resource_readiness(
    resource_id: UUID,
    request: Request,
) -> ResourceResponse:
    record = await request.app.state.resource_service.get(resource_id)
    return _response(record)


@router.get(
    "/projects/{project_id}/resources",
    response_model=ResourceListResponse,
    summary="List resources in one local project",
)
async def list_project_resources(
    project_id: UUID,
    request: Request,
) -> ResourceListResponse:
    records = await request.app.state.resource_service.list(project_id)
    link_records = await request.app.state.link_service.list(project_id)
    resources = [
        ResourceReadiness.from_record(record)
        for record in records
    ]
    from app.models.link import LinkReadiness

    links = [LinkReadiness.from_record(record) for record in link_records]
    return ResourceListResponse(
        project_id=project_id,
        resources=resources,
        links=links,
        eligible_count=sum(
            resource.eligible_for_analysis for resource in resources
        ) + sum(link.eligible_for_analysis for link in links),
    )


@router.delete(
    "/resources/{resource_id}",
    response_model=ResourceResponse,
    summary="Remove a resource from the project",
)
async def remove_resource(
    resource_id: UUID,
    request: Request,
) -> ResourceResponse:
    record = await request.app.state.resource_service.remove(resource_id)
    return _response(record)


@router.post(
    "/resources/{resource_id}/approve",
    response_model=ResourceResponse,
    summary="Include an irrelevant or duplicate resource anyway",
)
async def approve_resource(
    resource_id: UUID,
    request: Request,
) -> ResourceResponse:
    record = await request.app.state.resource_service.approve(resource_id)
    return _response(record)


@router.post(
    "/resources/{resource_id}/replacement",
    response_model=ResourceResponse,
    summary="Mark a resource for replacement",
)
async def mark_resource_for_replacement(
    resource_id: UUID,
    request: Request,
) -> ResourceResponse:
    record = await request.app.state.resource_service.mark_for_replacement(
        resource_id
    )
    return _response(record)
