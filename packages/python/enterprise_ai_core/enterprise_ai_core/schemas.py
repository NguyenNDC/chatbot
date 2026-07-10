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


class CanonicalBlock(BaseModel):
    id: str
    block_type: str
    order_index: int
    heading: str | None = None
    text: str
    page_start: int | None = None
    page_end: int | None = None
    metadata: dict[str, str | int | bool | None] = Field(default_factory=dict)


class CanonicalDocument(BaseModel):
    document_id: str
    document_version_id: str
    tenant_id: str
    title: str
    source_format: str
    language: str
    ocr_required: bool = False
    ocr_applied: bool = False
    plain_text: str
    blocks: list[CanonicalBlock]


class ChunkItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    document_id: str
    document_version_id: str
    tenant_id: str
    chunk_index: int
    section_name: str
    page_start: int | None = None
    page_end: int | None = None
    content: str
    token_estimate: int
    metadata: dict = Field(default_factory=dict)
    created_at: datetime | None = None


class EmbeddingRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    document_chunk_id: str
    model_name: str
    provider: str
    dimension: int
    created_at: datetime | None = None


class EntityItem(BaseModel):
    id: str
    canonical_name: str
    entity_type: str
    aliases: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    attributes: dict = Field(default_factory=dict)


class RelationItem(BaseModel):
    id: str
    source_entity_id: str
    target_entity_id: str
    relation_type: str
    confidence: float = 0.0
    evidence: str | None = None


class ChunkExtractionPayload(BaseModel):
    document_id: str
    document_chunk_id: str
    tenant_id: str
    entities: list[EntityItem] = Field(default_factory=list)
    relations: list[RelationItem] = Field(default_factory=list)
    summary: str = ""


class RuntimeHealthResponse(BaseModel):
    service: str
    runtime: str
    status: Literal["ok", "degraded", "error"]
    detail: str
    metadata: dict = Field(default_factory=dict)


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
