from uuid import uuid4

import httpx
from fastapi import APIRouter, Body, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response

from enterprise_ai_core.config import get_settings
from enterprise_ai_core.schemas import (
    DocumentDeleteResponse,
    DocumentListResponse,
    DocumentParsedPreviewResponse,
    DocumentReprocessRequest,
    DocumentVersionListResponse,
    GenerateAnswerResponse,
    ProcessingJobItem,
    ProcessingJobListResponse,
    QueryRequest,
    QueryResponse,
    TenantCreateRequest,
    TenantItem,
    TenantListResponse,
    UploadAcceptedResponse,
)

router = APIRouter(tags=["gateway"])
settings = get_settings()
REFERENTIAL_MARKERS = (
    "cai do",
    "cai nay",
    "van ban do",
    "noi dung do",
    "muc do",
    "muc nay",
    "the con",
    "con no",
    "it",
    "that",
    "those",
    "them",
    "what about",
)


def build_retrieval_question(payload: QueryRequest) -> str:
    question = " ".join(payload.question.split())
    lowered = question.lower()
    if not payload.conversation_history:
        return question

    should_expand = len(question) <= 80 or any(marker in lowered for marker in REFERENTIAL_MARKERS)
    if not should_expand:
        return question

    recent_user_turns = [
        turn.content.strip()
        for turn in payload.conversation_history
        if turn.role == "user" and turn.content.strip()
    ][-2:]
    if not recent_user_turns:
        return question

    return " ".join([*recent_user_turns, question])


@router.get("/documents", response_model=DocumentListResponse)
async def list_documents(tenant_id: str = Query(...)) -> DocumentListResponse:
    async with httpx.AsyncClient(timeout=settings.gateway_service_timeout_seconds) as client:
        response = await client.get(
            f"{settings.document_service_url}{settings.api_prefix}/documents",
            params={"tenant_id": tenant_id},
        )
    response.raise_for_status()
    return DocumentListResponse.model_validate(response.json())


@router.get("/tenants", response_model=TenantListResponse)
async def list_tenants() -> TenantListResponse:
    async with httpx.AsyncClient(timeout=settings.gateway_service_timeout_seconds) as client:
        response = await client.get(f"{settings.document_service_url}{settings.api_prefix}/tenants")
    response.raise_for_status()
    return TenantListResponse.model_validate(response.json())


@router.post("/tenants", response_model=TenantItem, status_code=201)
async def create_tenant(payload: TenantCreateRequest) -> TenantItem:
    async with httpx.AsyncClient(timeout=settings.gateway_service_timeout_seconds) as client:
        response = await client.post(
            f"{settings.document_service_url}{settings.api_prefix}/tenants",
            json=payload.model_dump(mode="json"),
        )
    response.raise_for_status()
    return TenantItem.model_validate(response.json())


@router.delete("/tenants/{tenant_id}", response_model=TenantItem)
async def delete_tenant(tenant_id: str) -> TenantItem:
    async with httpx.AsyncClient(timeout=settings.gateway_service_timeout_seconds) as client:
        response = await client.delete(
            f"{settings.document_service_url}{settings.api_prefix}/tenants/{tenant_id}"
        )
    response.raise_for_status()
    return TenantItem.model_validate(response.json())


@router.get("/documents/{document_id}/versions", response_model=DocumentVersionListResponse)
async def list_document_versions(
    document_id: str,
    tenant_id: str = Query(...),
) -> DocumentVersionListResponse:
    async with httpx.AsyncClient(timeout=settings.gateway_service_timeout_seconds) as client:
        response = await client.get(
            f"{settings.document_service_url}{settings.api_prefix}/documents/{document_id}/versions",
            params={"tenant_id": tenant_id},
        )
    response.raise_for_status()
    return DocumentVersionListResponse.model_validate(response.json())


@router.delete("/documents/{document_id}", response_model=DocumentDeleteResponse)
async def delete_document(
    document_id: str,
    tenant_id: str = Query(...),
) -> DocumentDeleteResponse:
    async with httpx.AsyncClient(timeout=settings.gateway_service_timeout_seconds) as client:
        response = await client.delete(
            f"{settings.document_service_url}{settings.api_prefix}/documents/{document_id}",
            params={"tenant_id": tenant_id},
        )
    response.raise_for_status()
    return DocumentDeleteResponse.model_validate(response.json())


@router.post("/documents/upload", response_model=UploadAcceptedResponse)
async def upload_document(
    tenant_id: str = Form(...),
    title: str = Form(...),
    tags: str = Form(default=""),
    file: UploadFile = File(...),
) -> UploadAcceptedResponse:
    payload = await file.read()
    async with httpx.AsyncClient(timeout=settings.gateway_service_timeout_seconds) as client:
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
    tenant_id: str = Form(...),
    title: str | None = Form(default=None),
    tags: str = Form(default=""),
    effective_from: str | None = Form(default=None),
    file: UploadFile = File(...),
) -> UploadAcceptedResponse:
    payload = await file.read()
    data = {"tenant_id": tenant_id, "tags": tags}
    if title is not None:
        data["title"] = title
    if effective_from is not None:
        data["effective_from"] = effective_from
    async with httpx.AsyncClient(timeout=settings.gateway_service_timeout_seconds) as client:
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
    tenant_id: str = Query(...),
) -> ProcessingJobItem:
    async with httpx.AsyncClient(timeout=settings.gateway_service_timeout_seconds) as client:
        response = await client.post(
            f"{settings.document_service_url}{settings.api_prefix}/documents/{document_id}/reprocess",
            params={"tenant_id": tenant_id},
            json=payload.model_dump(mode="json"),
        )
    response.raise_for_status()
    return ProcessingJobItem.model_validate(response.json())


@router.get("/documents/{document_id}/preview/raw")
async def preview_raw_document(document_id: str, tenant_id: str = Query(...)) -> Response:
    async with httpx.AsyncClient(timeout=max(60, settings.gateway_service_timeout_seconds)) as client:
        response = await client.get(
            f"{settings.document_service_url}{settings.api_prefix}/documents/{document_id}/preview/raw",
            params={"tenant_id": tenant_id},
        )
    response.raise_for_status()
    headers = {}
    content_type = response.headers.get("content-type", "application/octet-stream")
    content_disposition = response.headers.get("content-disposition")
    if content_disposition:
        headers["Content-Disposition"] = content_disposition
    return Response(content=response.content, media_type=content_type, headers=headers)


@router.get("/documents/{document_id}/preview/parsed", response_model=DocumentParsedPreviewResponse)
async def preview_parsed_document(
    document_id: str,
    tenant_id: str = Query(...),
) -> DocumentParsedPreviewResponse:
    async with httpx.AsyncClient(timeout=settings.gateway_service_timeout_seconds) as client:
        response = await client.get(
            f"{settings.document_service_url}{settings.api_prefix}/documents/{document_id}/preview/parsed",
            params={"tenant_id": tenant_id},
        )
    response.raise_for_status()
    return DocumentParsedPreviewResponse.model_validate(response.json())


@router.post("/query", response_model=QueryResponse)
async def query(payload: QueryRequest) -> QueryResponse:
    trace_id = str(uuid4())
    retrieval_question = build_retrieval_question(payload)
    retrieval_payload = payload.model_copy(update={"question": retrieval_question})
    try:
        async with httpx.AsyncClient(timeout=settings.gateway_query_retrieval_timeout_seconds) as client:
            retrieval_response = await client.post(
                f"{settings.retrieval_service_url}{settings.api_prefix}/retrieve",
                json=retrieval_payload.model_dump(mode="json"),
            )
        retrieval_response.raise_for_status()
        retrieval_data = retrieval_response.json()
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="Retrieval service timed out") from exc

    try:
        async with httpx.AsyncClient(timeout=settings.gateway_query_llm_timeout_seconds) as client:
            llm_response = await client.post(
                f"{settings.llm_service_url}{settings.api_prefix}/generate",
                json={
                    "tenant_id": payload.tenant_id,
                    "question": payload.question,
                    "contexts": retrieval_data["contexts"],
                    "retrieval_plan": retrieval_data.get("plan", {}),
                    "conversation_history": [turn.model_dump(mode="json") for turn in payload.conversation_history],
                },
            )
        llm_response.raise_for_status()
        answer = GenerateAnswerResponse.model_validate(llm_response.json())
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="Chatbot answer generation timed out") from exc

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

    async with httpx.AsyncClient(timeout=min(10, settings.gateway_service_timeout_seconds)) as client:
        for name, base_url in services.items():
            try:
                response = await client.get(f"{base_url}/health")
                checks[name] = response.json()
            except httpx.HTTPError as exc:
                checks[name] = {"service": name, "status": "unavailable", "detail": str(exc)}

    status = "ok" if all(item.get("status") == "ok" for item in checks.values()) else "degraded"
    return {"status": status, "services": checks}


@router.get("/jobs", response_model=ProcessingJobListResponse)
async def list_jobs(tenant_id: str = Query(...)) -> ProcessingJobListResponse:
    async with httpx.AsyncClient(timeout=settings.gateway_service_timeout_seconds) as client:
        response = await client.get(
            f"{settings.worker_service_url}{settings.api_prefix}/jobs",
            params={"tenant_id": tenant_id},
        )
    response.raise_for_status()
    return ProcessingJobListResponse.model_validate(response.json())


@router.get("/jobs/{job_id}", response_model=ProcessingJobItem)
async def get_job(job_id: str, tenant_id: str = Query(...)) -> ProcessingJobItem:
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(
            f"{settings.worker_service_url}{settings.api_prefix}/jobs/{job_id}",
            params={"tenant_id": tenant_id},
        )
    response.raise_for_status()
    return ProcessingJobItem.model_validate(response.json())
