from datetime import datetime, timezone
from enum import StrEnum
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


class AnswerDisposition(StrEnum):
    GROUNDED = "grounded"
    PARTIAL = "partial"
    NO_ANSWER = "no_answer"
    REFUSAL = "refusal"
    CLARIFICATION = "clarification"


class HealthResponse(BaseModel):
    service: str
    status: Literal["ok"] = "ok"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class TenantItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    display_name: str
    description: str | None = None
    status: str = "active"
    document_count: int = 0
    created_at: datetime


class TenantCreateRequest(BaseModel):
    id: str
    display_name: str
    description: str | None = None


class TenantListResponse(BaseModel):
    items: list[TenantItem]
    total: int


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
    current_job_id: str | None = None
    current_job_type: str | None = None
    current_job_status: JobStatus | None = None
    current_job_error_message: str | None = None
    processing_stage: str | None = None
    processing_stage_label: str | None = None
    processing_stage_status: JobStatus | None = None
    processing_progress_percent: int = 0
    processing_progress_current: int | None = None
    processing_progress_total: int | None = None
    processing_progress_label: str = ""
    processing_progress_detail: str | None = None
    processing_mode: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DocumentVersionItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    document_id: str
    version_label: str
    version_number: int
    checksum_sha256: str
    size_bytes: int
    status: str
    processing_scope: str
    is_current: bool
    effective_from: datetime
    effective_to: datetime | None = None
    parse_quality_score: float | None = None
    created_at: datetime


class DocumentCreateRequest(BaseModel):
    tenant_id: str
    title: str
    file_name: str
    content_type: str
    tags: list[str] = Field(default_factory=list)


class DocumentListResponse(BaseModel):
    items: list[DocumentItem]
    total: int


class DocumentVersionListResponse(BaseModel):
    items: list[DocumentVersionItem]
    total: int


class DocumentParsedPreviewResponse(BaseModel):
    document_id: str
    document_version_id: str
    version_label: str
    title: str
    language: str
    ocr_required: bool = False
    ocr_applied: bool = False
    parse_quality_score: float = 0.0
    parse_warnings: list[str] = Field(default_factory=list)
    plain_text: str = ""


class DocumentDeleteResponse(BaseModel):
    document_id: str
    tenant_id: str
    title: str
    deleted: bool = True


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
    stage_label: str | None = None
    version_label: str | None = None
    processing_mode: str | None = None
    progress_percent: int = 0
    progress_current: int | None = None
    progress_total: int | None = None
    progress_label: str = ""
    progress_detail: str | None = None


class ProcessingJobListResponse(BaseModel):
    items: list[ProcessingJobItem]
    total: int


class CanonicalBlock(BaseModel):
    id: str
    block_type: str
    order_index: int
    heading: str | None = None
    heading_path: list[str] = Field(default_factory=list)
    parent_block_id: str | None = None
    text: str
    page_start: int | None = None
    page_end: int | None = None
    source_offset_start: int | None = None
    source_offset_end: int | None = None
    table_id: str | None = None
    row_index: int | None = None
    cell_index: int | None = None
    parse_quality_score: float | None = None
    ocr_confidence: float | None = None
    metadata: dict[str, str | int | float | bool | None | list[str]] = Field(default_factory=dict)


class CanonicalDocument(BaseModel):
    document_id: str
    document_version_id: str
    tenant_id: str
    title: str
    source_format: str
    language: str
    ocr_required: bool = False
    ocr_applied: bool = False
    parse_quality_score: float = 0.0
    parse_warnings: list[str] = Field(default_factory=list)
    plain_text: str
    metadata: dict[str, str | int | float | bool | None | list[str]] = Field(default_factory=dict)
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
    source_offset_start: int | None = None
    source_offset_end: int | None = None
    heading_path: list[str] = Field(default_factory=list)
    content: str
    token_estimate: int
    parse_quality_score: float | None = None
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


class UploadAcceptedResponse(BaseModel):
    document: DocumentItem
    root_job: ProcessingJobItem
    object_key: str
    version: DocumentVersionItem | None = None


class DocumentReprocessRequest(BaseModel):
    document_version_id: str | None = None
    mode: Literal["incremental", "full"] = "incremental"
    reason: str = "manual_reprocess"


class Citation(BaseModel):
    document_id: str
    document_version_id: str | None = None
    title: str
    section: str
    section_path: list[str] = Field(default_factory=list)
    page: int | None = None
    chunk_id: str
    block_id: str | None = None


class RetrievalChunk(BaseModel):
    chunk_id: str
    score: float
    content: str
    source: Citation
    retrieval_source: str = "vector"
    vector_score: float | None = None
    graph_score: float | None = None
    re_rank_score: float | None = None
    final_score: float | None = None
    supporting_entities: list[str] = Field(default_factory=list)
    query_path: list[str] = Field(default_factory=list)


class ConversationTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatSessionItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    title: str
    status: str = "active"
    message_count: int = 0
    last_message_at: datetime | None = None
    last_message_preview: str | None = None
    created_at: datetime
    updated_at: datetime


class ChatSessionCreateRequest(BaseModel):
    tenant_id: str
    title: str | None = None


class ChatSessionListResponse(BaseModel):
    items: list[ChatSessionItem]
    total: int


class ChatMessageItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    session_id: str
    tenant_id: str
    role: Literal["user", "assistant", "system"]
    content: str
    answer_type: str | None = None
    citations: list["Citation"] = Field(default_factory=list)
    contexts: list["RetrievalChunk"] = Field(default_factory=list)
    policy_summary: list[str] = Field(default_factory=list)
    clarification_question: str | None = None
    refusal_reason: str | None = None
    trace_id: str | None = None
    created_at: datetime


class ChatMessageCreateRequest(BaseModel):
    tenant_id: str
    role: Literal["user", "assistant", "system"]
    content: str
    answer_type: str | None = None
    citations: list["Citation"] = Field(default_factory=list)
    contexts: list["RetrievalChunk"] = Field(default_factory=list)
    policy_summary: list[str] = Field(default_factory=list)
    clarification_question: str | None = None
    refusal_reason: str | None = None
    trace_id: str | None = None


class ChatMessageListResponse(BaseModel):
    items: list[ChatMessageItem]
    total: int


class ChatSendMessageRequest(BaseModel):
    tenant_id: str
    message: str
    query_mode: Literal["auto", "lookup", "summary", "compare", "temporal"] = "auto"
    top_k: int = 6
    include_graph: bool = True
    include_summaries: bool = True


class ChatSendMessageResponse(BaseModel):
    session: ChatSessionItem
    user_message: ChatMessageItem
    assistant_message: ChatMessageItem


class QueryRequest(BaseModel):
    tenant_id: str
    question: str
    top_k: int = 6
    include_graph: bool = True
    include_summaries: bool = True
    query_mode: Literal["auto", "lookup", "summary", "compare", "temporal"] = "auto"
    document_ids: list[str] = Field(default_factory=list)
    version_ids: list[str] = Field(default_factory=list)
    effective_at: datetime | None = None
    conversation_history: list["ConversationTurn"] = Field(default_factory=list)


class QueryResponse(BaseModel):
    trace_id: str
    question: str
    answer: str
    answer_type: AnswerDisposition = AnswerDisposition.GROUNDED
    citations: list[Citation]
    contexts: list[RetrievalChunk]
    policy_summary: list[str] = Field(default_factory=list)
    clarification_question: str | None = None


class GenerateAnswerRequest(BaseModel):
    tenant_id: str
    question: str
    contexts: list[RetrievalChunk]
    retrieval_plan: dict = Field(default_factory=dict)
    conversation_history: list["ConversationTurn"] = Field(default_factory=list)


class GenerateAnswerResponse(BaseModel):
    trace_id: str
    model: str
    answer: str
    answer_type: AnswerDisposition = AnswerDisposition.GROUNDED
    citations: list[Citation]
    policy_summary: list[str] = Field(default_factory=list)
    clarification_question: str | None = None
    refusal_reason: str | None = None
