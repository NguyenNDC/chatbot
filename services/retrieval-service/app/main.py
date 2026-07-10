from contextlib import asynccontextmanager

from fastapi import FastAPI

from enterprise_ai_core.config import get_settings
from enterprise_ai_core.logging import configure_logging

from routers import health, retrieval

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging(settings.service_name)
    yield


app = FastAPI(
    title="Retrieval Service",
    version="0.1.0",
    lifespan=lifespan,
    openapi_url=f"{settings.api_prefix}/openapi.json",
    docs_url="/docs",
)
app.include_router(health.router)
app.include_router(retrieval.router, prefix=settings.api_prefix)
