from uuid import uuid4

import httpx
from fastapi import APIRouter, File, Form, UploadFile

from enterprise_ai_core.config import get_settings
from enterprise_ai_core.schemas import (
    DocumentListResponse,
    GenerateAnswerResponse,
    ProcessingJobItem,
    ProcessingJobListResponse,
    QueryRequest,
    QueryResponse,
    UploadAcceptedResponse,
)

router = APIRouter(tags=["gateway"])
settings = get_settings()


@router.get("/documents", response_model=DocumentListResponse)
async def list_documents() -> DocumentListResponse:
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(f"{settings.document_service_url}{settings.api_prefix}/documents")
    response.raise_for_status()
    return DocumentListResponse.model_validate(response.json())


@router.post("/documents/upload", response_model=UploadAcceptedResponse)
async def upload_document(
    tenant_id: str = Form(...),
    title: str = Form(...),
    tags: str = Form(default=""),
    file: UploadFile = File(...),
) -> UploadAcceptedResponse:
    payload = await file.read()
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            f"{settings.document_service_url}{settings.api_prefix}/documents/upload",
            data={"tenant_id": tenant_id, "title": title, "tags": tags},
            files={
                "file": (
                    file.filename or "upload.bin",
                    payload,
                    file.content_type or "application/octet-stream",
                )
            },
        )
    response.raise_for_status()
    return UploadAcceptedResponse.model_validate(response.json())


@router.post("/query", response_model=QueryResponse)
async def query(payload: QueryRequest) -> QueryResponse:
    trace_id = str(uuid4())
    async with httpx.AsyncClient(timeout=30) as client:
        retrieval_response = await client.post(
            f"{settings.retrieval_service_url}{settings.api_prefix}/retrieve",
            json=payload.model_dump(),
        )
        retrieval_response.raise_for_status()
        retrieval_data = retrieval_response.json()

        llm_response = await client.post(
            f"{settings.llm_service_url}{settings.api_prefix}/generate",
            json={
                "tenant_id": payload.tenant_id,
                "question": payload.question,
                "contexts": retrieval_data["contexts"],
            },
        )
        llm_response.raise_for_status()
        answer = GenerateAnswerResponse.model_validate(llm_response.json())

    return QueryResponse(
        trace_id=trace_id,
        question=payload.question,
        answer=answer.answer,
        citations=answer.citations,
        contexts=retrieval_data["contexts"],
    )


@router.get("/system/overview")
async def system_overview() -> dict:
    services = {
        "document_service": settings.document_service_url,
        "retrieval_service": settings.retrieval_service_url,
        "graph_service": settings.graph_service_url,
        "llm_service": settings.llm_service_url,
        "worker_service": settings.worker_service_url,
    }
    checks: dict[str, dict] = {}

    async with httpx.AsyncClient(timeout=10) as client:
        for name, base_url in services.items():
            try:
                response = await client.get(f"{base_url}/health")
                checks[name] = response.json()
            except httpx.HTTPError as exc:
                checks[name] = {"service": name, "status": "unavailable", "detail": str(exc)}

    status = "ok" if all(item.get("status") == "ok" for item in checks.values()) else "degraded"
    return {"status": status, "services": checks}


@router.get("/jobs", response_model=ProcessingJobListResponse)
async def list_jobs() -> ProcessingJobListResponse:
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(f"{settings.worker_service_url}{settings.api_prefix}/jobs")
    response.raise_for_status()
    return ProcessingJobListResponse.model_validate(response.json())


@router.get("/jobs/{job_id}", response_model=ProcessingJobItem)
async def get_job(job_id: str) -> ProcessingJobItem:
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(f"{settings.worker_service_url}{settings.api_prefix}/jobs/{job_id}")
    response.raise_for_status()
    return ProcessingJobItem.model_validate(response.json())
