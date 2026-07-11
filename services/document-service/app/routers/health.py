from fastapi import APIRouter

from enterprise_ai_core.config import get_settings
from enterprise_ai_core.schemas import HealthResponse, RuntimeHealthResponse

router = APIRouter(tags=["health"])
settings = get_settings()


@router.get("/health", response_model=HealthResponse)
async def healthcheck() -> HealthResponse:
    return HealthResponse(service=settings.service_name)


@router.get("/health/ocr")
async def ocr_healthcheck() -> dict:
    try:
        from enterprise_ai_core.parsing import ocr_runtime_health
    except ImportError as exc:
        return RuntimeHealthResponse(
            service=settings.service_name,
            runtime="ocr",
            status="degraded",
            detail=f"OCR runtime is not installed in this image: {exc}",
            metadata={"engine": settings.ocr_engine, "languages": settings.ocr_languages},
        ).model_dump(mode="json")

    return ocr_runtime_health(settings.service_name).model_dump(mode="json")
