from contextlib import asynccontextmanager

from fastapi import FastAPI

from enterprise_ai_core.config import get_settings
from enterprise_ai_core.db import init_db
from enterprise_ai_core.logging import configure_logging
from enterprise_ai_core.storage import RustFSStorageClient

from routers import documents, health

settings = get_settings()
storage_client = RustFSStorageClient()


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging(settings.service_name)
    init_db()
    storage_client.ensure_bucket(settings.rustfs_bucket_raw)
    storage_client.ensure_bucket(settings.rustfs_bucket_artifacts)
    yield


app = FastAPI(
    title="Document Service",
    version="0.1.0",
    lifespan=lifespan,
    openapi_url=f"{settings.api_prefix}/openapi.json",
    docs_url="/docs",
)
app.include_router(health.router)
app.include_router(documents.router, prefix=settings.api_prefix)
