from contextlib import asynccontextmanager

from fastapi import FastAPI

from enterprise_ai_core.config import get_settings
from enterprise_ai_core.graphdb import get_neo4j_client
from enterprise_ai_core.logging import configure_logging

from routers import graph, health

settings = get_settings()
neo4j_client = get_neo4j_client()


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging(settings.service_name)
    neo4j_client.ensure_schema()
    try:
        yield
    finally:
        neo4j_client.close()


app = FastAPI(
    title="Graph Service",
    version="0.1.0",
    lifespan=lifespan,
    openapi_url=f"{settings.api_prefix}/openapi.json",
    docs_url="/docs",
)
app.include_router(health.router)
app.include_router(graph.router, prefix=settings.api_prefix)
