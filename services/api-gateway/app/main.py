from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from enterprise_ai_core.config import get_settings
from enterprise_ai_core.logging import configure_logging

from routers import health, orchestration

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging(settings.service_name)
    yield


app = FastAPI(
    title="API Gateway",
    version="0.1.0",
    lifespan=lifespan,
    openapi_url=f"{settings.api_prefix}/openapi.json",
    docs_url="/docs",
)

cors_origins = [item.strip() for item in settings.cors_allow_origins.split(",") if item.strip()]
if settings.app_public_url not in cors_origins:
    cors_origins.append(settings.app_public_url)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(orchestration.router, prefix=settings.api_prefix)
