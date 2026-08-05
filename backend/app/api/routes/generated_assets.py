"""Generated asset version, restore, compare, and download endpoints."""

from uuid import UUID

from fastapi import APIRouter, Query, Request, Response

from app.models.generated_asset import (
    AssetListResponse,
    CompareVersionsResponse,
    GeneratedAsset,
    RegenerateAssetRequest,
)

router = APIRouter(prefix="/api/v1", tags=["generated-assets"])


@router.get(
    "/action-packs/{pack_id}/assets",
    response_model=AssetListResponse,
)
async def list_generated_assets(
    pack_id: UUID,
    request: Request,
) -> AssetListResponse:
    return await request.app.state.generated_asset_service.list_response(pack_id)


@router.post(
    "/generated-assets/{asset_id}/regenerate",
    response_model=GeneratedAsset,
)
async def regenerate_asset(
    asset_id: UUID,
    body: RegenerateAssetRequest,
    request: Request,
) -> GeneratedAsset:
    return await request.app.state.generated_asset_service.regenerate(
        asset_id,
        body,
    )


@router.post(
    "/generated-assets/{asset_id}/versions/{version_number}/restore",
    response_model=GeneratedAsset,
)
async def restore_asset_version(
    asset_id: UUID,
    version_number: int,
    request: Request,
) -> GeneratedAsset:
    return await request.app.state.generated_asset_service.restore(
        asset_id,
        version_number,
    )


@router.get(
    "/generated-assets/{asset_id}/compare",
    response_model=CompareVersionsResponse,
)
async def compare_asset_versions(
    asset_id: UUID,
    request: Request,
    left: int = Query(ge=1),
    right: int = Query(ge=1),
) -> CompareVersionsResponse:
    return await request.app.state.generated_asset_service.compare(
        asset_id,
        left,
        right,
    )


@router.get(
    "/generated-assets/{asset_id}/versions/{version_number}/download",
)
async def download_asset_version(
    asset_id: UUID,
    version_number: int,
    request: Request,
) -> Response:
    data, content_type, filename = (
        await request.app.state.generated_asset_service.download_version(
            asset_id,
            version_number,
        )
    )
    return Response(
        content=data,
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/action-packs/{pack_id}/download.zip")
async def download_combined_pack(pack_id: UUID, request: Request) -> Response:
    data, filename = (
        await request.app.state.generated_asset_service.combined_zip(pack_id)
    )
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
