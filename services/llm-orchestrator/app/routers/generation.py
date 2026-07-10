from uuid import uuid4

from fastapi import APIRouter

from enterprise_ai_core.config import get_settings
from enterprise_ai_core.schemas import GenerateAnswerRequest, GenerateAnswerResponse

router = APIRouter(tags=["generation"])
settings = get_settings()


@router.post("/generate", response_model=GenerateAnswerResponse)
async def generate_answer(payload: GenerateAnswerRequest) -> GenerateAnswerResponse:
    first_citation = payload.contexts[0].source if payload.contexts else None
    answer = (
        "Theo cac tai lieu duoc truy xuat, doanh nghiep co nghia vu cap PPE phu hop "
        "cho nguoi lao dong va luu vet viec cap phat. He thong hien dang tra ve ket qua "
        "tu retrieval grounding; adapter OpenRouter co the thay the phan sinh cau tra loi nay."
    )
    return GenerateAnswerResponse(
        trace_id=str(uuid4()),
        model=settings.openrouter_model_primary,
        answer=answer,
        citations=[first_citation] if first_citation else [],
        policy_summary=[
            "grounded-answer-only",
            "cite-source-required",
            "permission-aware-response",
        ],
    )

