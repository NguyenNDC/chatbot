from contextlib import asynccontextmanager

from fastapi import FastAPI

from enterprise_ai_core.config import get_settings
from enterprise_ai_core.db import init_db
from enterprise_ai_core.logging import configure_logging

from routers import health, jobs

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging(settings.service_name)
    init_db()
    yield


app = FastAPI(
    title="Worker Control API",
    version="0.1.0",
    lifespan=lifespan,
    openapi_url=f"{settings.api_prefix}/openapi.json",
    docs_url="/docs",
)
app.include_router(health.router)
app.include_router(jobs.router, prefix=settings.api_prefix)

