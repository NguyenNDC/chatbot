from contextlib import asynccontextmanager

from fastapi import FastAPI

from enterprise_ai_core.config import get_settings
from enterprise_ai_core.logging import configure_logging, install_request_logging

from routers import generation, health

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging(settings.service_name)
    yield


app = FastAPI(
    title="LLM Orchestrator",
    version="0.1.0",
    lifespan=lifespan,
    openapi_url=f"{settings.api_prefix}/openapi.json",
    docs_url="/docs",
)
install_request_logging(app, settings.service_name)
app.include_router(health.router)
app.include_router(generation.router, prefix=settings.api_prefix)
