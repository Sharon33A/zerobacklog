"""FastAPI application factory and ASGI entry point."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.services.uploads import UploadService

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create a configured FastAPI application."""
    app_settings = settings or get_settings()
    configure_logging(app_settings.log_level)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        logger.info(
            "Starting service=%s version=%s environment=%s",
            app_settings.service_name,
            app_settings.app_version,
            app_settings.app_env,
        )
        yield
        application.state.upload_service.close()
        logger.info("Stopping service=%s", app_settings.service_name)

    application = FastAPI(
        title="ZeroBacklog API",
        description="Backend foundation for the ZeroBacklog learning pipeline.",
        version=app_settings.app_version,
        lifespan=lifespan,
    )
    application.state.settings = app_settings
    application.state.upload_service = UploadService(app_settings)

    application.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Accept", "Content-Type"],
    )
    register_exception_handlers(application)
    application.include_router(api_router)
    return application


app = create_app()
