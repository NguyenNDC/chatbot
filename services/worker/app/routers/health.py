from fastapi import APIRouter

from enterprise_ai_core.config import get_settings
from enterprise_ai_core.schemas import HealthResponse

router = APIRouter(tags=["health"])
settings = get_settings()


@router.get("/health", response_model=HealthResponse)
async def healthcheck() -> HealthResponse:
    return HealthResponse(service=settings.service_name)
