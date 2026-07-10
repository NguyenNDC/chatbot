from enum import StrEnum
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class DocumentStatus(StrEnum):
    UPLOADED = "uploaded"
    QUEUED = "queued"
    PROCESSING = "processing"
    PROCESSED = "processed"
    FAILED = "failed"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class HealthResponse(BaseModel):
    service: str
    status: Literal["ok"] = "ok"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DocumentItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str = Field(default_factory=lambda: str(uuid4()))
    tenant_id: str
    title: str
    file_name: str
    content_type: str
    status: DocumentStatus = DocumentStatus.UPLOADED
    version: str = "v1"
    tags: list[str] = Field(default_factory=list)
    source: str = "rustfs"
    checksum_sha256: str | None = None
    size_bytes: int | None = None
    current_job_type: str | None = None
    current_job_status: JobStatus | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DocumentCreateRequest(BaseModel):
    tenant_id: str
    title: str
    file_name: str
    content_type: str
    tags: list[str] = Field(default_factory=list)


class DocumentListResponse(BaseModel):
    items: list[DocumentItem]
    total: int


class ProcessingJobItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    document_id: str
    job_type: str
    queue_name: str
    status: JobStatus
    celery_task_id: str | None = None
    attempts: int = 0
    error_message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    parent_job_id: str | None = None


class ProcessingJobListResponse(BaseModel):
    items: list[ProcessingJobItem]
    total: int


class DocumentUploadResponse(BaseModel):
    document: DocumentItem
    root_job: ProcessingJobItem


class UploadAcceptedResponse(BaseModel):
    document: DocumentItem
    root_job: ProcessingJobItem
    object_key: str


class Citation(BaseModel):
    document_id: str
    title: str
    section: str
    page: int | None = None
    chunk_id: str


class RetrievalChunk(BaseModel):
    chunk_id: str
    score: float
    content: str
    source: Citation


class QueryRequest(BaseModel):
    tenant_id: str
    question: str
    top_k: int = 6
    include_graph: bool = True
    include_summaries: bool = True


class QueryResponse(BaseModel):
    trace_id: str
    question: str
    answer: str
    citations: list[Citation]
    contexts: list[RetrievalChunk]


class GenerateAnswerRequest(BaseModel):
    tenant_id: str
    question: str
    contexts: list[RetrievalChunk]


class GenerateAnswerResponse(BaseModel):
    trace_id: str
    model: str
    answer: str
    citations: list[Citation]
    policy_summary: list[str] = Field(default_factory=list)
