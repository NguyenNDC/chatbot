from uuid import uuid4

import httpx
from fastapi import APIRouter, Body, File, Form, UploadFile

from enterprise_ai_core.config import get_settings
from enterprise_ai_core.schemas import (
    DocumentListResponse,
    DocumentReprocessRequest,
    DocumentVersionListResponse,
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


@router.get("/documents/{document_id}/versions", response_model=DocumentVersionListResponse)
async def list_document_versions(document_id: str) -> DocumentVersionListResponse:
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(
            f"{settings.document_service_url}{settings.api_prefix}/documents/{document_id}/versions"
        )
    response.raise_for_status()
    return DocumentVersionListResponse.model_validate(response.json())


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


@router.post("/documents/{document_id}/versions/upload", response_model=UploadAcceptedResponse)
async def upload_document_version(
    document_id: str,
    title: str | None = Form(default=None),
    tags: str = Form(default=""),
    effective_from: str | None = Form(default=None),
    file: UploadFile = File(...),
) -> UploadAcceptedResponse:
    payload = await file.read()
    data = {"tags": tags}
    if title is not None:
        data["title"] = title
    if effective_from is not None:
        data["effective_from"] = effective_from
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            f"{settings.document_service_url}{settings.api_prefix}/documents/{document_id}/versions/upload",
            data=data,
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


@router.post("/documents/{document_id}/reprocess", response_model=ProcessingJobItem)
async def reprocess_document(
    document_id: str,
    payload: DocumentReprocessRequest = Body(...),
) -> ProcessingJobItem:
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            f"{settings.document_service_url}{settings.api_prefix}/documents/{document_id}/reprocess",
            json=payload.model_dump(mode="json"),
        )
    response.raise_for_status()
    return ProcessingJobItem.model_validate(response.json())


@router.post("/query", response_model=QueryResponse)
async def query(payload: QueryRequest) -> QueryResponse:
    trace_id = str(uuid4())
    async with httpx.AsyncClient(timeout=40) as client:
        retrieval_response = await client.post(
            f"{settings.retrieval_service_url}{settings.api_prefix}/retrieve",
            json=payload.model_dump(mode="json"),
        )
        retrieval_response.raise_for_status()
        retrieval_data = retrieval_response.json()

        llm_response = await client.post(
            f"{settings.llm_service_url}{settings.api_prefix}/generate",
            json={
                "tenant_id": payload.tenant_id,
                "question": payload.question,
                "contexts": retrieval_data["contexts"],
                "retrieval_plan": retrieval_data.get("plan", {}),
            },
        )
        llm_response.raise_for_status()
        answer = GenerateAnswerResponse.model_validate(llm_response.json())

    return QueryResponse(
        trace_id=trace_id,
        question=payload.question,
        answer=answer.answer,
        answer_type=answer.answer_type,
        citations=answer.citations,
        contexts=retrieval_data["contexts"],
        policy_summary=answer.policy_summary,
        clarification_question=answer.clarification_question,
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
