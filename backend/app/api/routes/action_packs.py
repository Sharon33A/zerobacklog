"""Cross-resource Gemini knowledge-reduction endpoints."""

from uuid import UUID

from fastapi import APIRouter, Request

from app.models.action_pack import (
    ActionPackCreateRequest,
    ActionPackResponse,
)

router = APIRouter(prefix="/api/v1", tags=["action-packs"])


@router.post(
    "/projects/{project_id}/action-packs",
    response_model=ActionPackResponse,
    summary="Build an evidence-first Action Pack",
)
async def create_action_pack(
    project_id: UUID,
    body: ActionPackCreateRequest,
    request: Request,
) -> ActionPackResponse:
    result = await request.app.state.action_pack_service.generate(
        project_id,
        body.learner_profile,
        body.output_options,
    )
    assets = await request.app.state.generated_asset_service.generate_selected(
        result,
        body,
    )
    return result.model_copy(update={"assets": assets})


@router.get(
    "/projects/{project_id}/action-packs/latest",
    response_model=ActionPackResponse,
    summary="Retrieve the latest completed Action Pack",
)
async def get_latest_action_pack(
    project_id: UUID,
    request: Request,
) -> ActionPackResponse:
    result = await request.app.state.action_pack_service.latest(project_id)
    assets = await request.app.state.generated_asset_service.list_assets(result.id)
    return result.model_copy(update={"assets": assets})
