"""Application API router."""

from fastapi import APIRouter

from app.api.routes import (
    action_packs,
    generated_assets,
    health,
    links,
    resources,
    uploads,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(uploads.router)
api_router.include_router(resources.router)
api_router.include_router(links.router)
api_router.include_router(action_packs.router)
api_router.include_router(generated_assets.router)
