import json
import logging
from datetime import datetime, timezone
from pathlib import PurePosixPath

from sqlalchemy import delete, select

from enterprise_ai_core.chunking import blocks_to_chunks, chunk_hash
from enterprise_ai_core.config import get_settings
from enterprise_ai_core.db import SessionLocal
from enterprise_ai_core.embedding import get_embedding_provider
from enterprise_ai_core.extraction import run_chunk_extraction
from enterprise_ai_core.graph_upsert import clear_document_graph, upsert_extraction_payload
from enterprise_ai_core.graphdb import get_neo4j_client
from enterprise_ai_core.models import (
    ChunkEmbedding,
    ChunkExtraction,
    Document,
    DocumentArtifact,
    DocumentChunk,
    DocumentVersion,
    ProcessingJob,
)
from enterprise_ai_core.openrouter import OpenRouterClient
from enterprise_ai_core.parsing import build_canonical_document
from enterprise_ai_core.queue import get_celery_app
from enterprise_ai_core.schemas import CanonicalDocument, ChunkExtractionPayload, DocumentStatus, JobStatus
from enterprise_ai_core.storage import RustFSStorageClient

celery_app = get_celery_app()
settings = get_settings()
storage_client = RustFSStorageClient()
embedding_provider = get_embedding_provider()
openrouter_client = OpenRouterClient()
neo4j_client = get_neo4j_client()
logger = logging.getLogger(__name__)

NEXT_STAGE: dict[str, str | None] = {
    "document.parse": "document.chunk",
    "document.chunk": "document.embed",
    "document.embed": "graph.extract",
    "graph.extract": "graph.upsert",
    "graph.upsert": None,
}
DEAD_LETTER_TASK_NAME = "document.dead_letter"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def get_current_version(session, document_id: str) -> DocumentVersion:
    version = session.scalars(
        select(DocumentVersion)
        .where(DocumentVersion.document_id == document_id)
        .order_by(DocumentVersion.created_at.desc())
    ).first()
    if not version:
        raise ValueError(f"No document version found for document {document_id}")
    return version


def upsert_artifact(
    *,
    session,
    document_id: str,
    document_version_id: str,
    artifact_type: str,
    bucket_name: str,
    object_key: str,
    content_type: str,
) -> DocumentArtifact:
    artifact = session.scalars(
        select(DocumentArtifact).where(
            DocumentArtifact.document_version_id == document_version_id,
            DocumentArtifact.artifact_type == artifact_type,
        )
    ).first()
    if artifact:
        artifact.bucket_name = bucket_name
        artifact.object_key = object_key
        artifact.content_type = content_type
        session.add(artifact)
        return artifact

    artifact = DocumentArtifact(
        document_id=document_id,
        document_version_id=document_version_id,
        artifact_type=artifact_type,
        bucket_name=bucket_name,
        object_key=object_key,
        content_type=content_type,
    )
    session.add(artifact)
    return artifact


def enqueue_next_stage(
    *,
    current_job: ProcessingJob,
    document: Document,
    next_stage: str,
) -> None:
    session = SessionLocal()
    try:
        next_job = ProcessingJob(
            tenant_id=document.tenant_id,
            document_id=document.id,
            parent_job_id=current_job.id,
            job_type=next_stage,
            queue_name=next_stage,
            status=JobStatus.QUEUED.value,
            payload={"previous_job_id": current_job.id},
        )
        session.add(next_job)
        session.commit()
        session.refresh(next_job)

        try:
            result = celery_app.send_task(
                next_stage,
                kwargs={
                    "job_id": next_job.id,
                    "document_id": document.id,
                    "tenant_id": document.tenant_id,
                },
                queue=next_stage,
            )
            next_job.celery_task_id = result.id
            session.add(next_job)
            session.commit()
        except Exception as exc:
            session.rollback()
            next_job.status = JobStatus.FAILED.value
            next_job.error_message = f"Failed to enqueue next stage: {exc}"
            document.status = DocumentStatus.FAILED.value
            session.add(next_job)
            session.add(document)
            session.commit()
            raise
    finally:
        session.close()


def schedule_retry(*, stage_name: str, job_id: str, document_id: str, error_message: str) -> None:
    session = SessionLocal()
    try:
        job = session.get(ProcessingJob, job_id)
        document = session.get(Document, document_id)
        if job is not None:
            job.status = JobStatus.QUEUED.value
            job.error_message = error_message
            job.completed_at = None
            job.payload = {
                **job.payload,
                "last_retry_error": error_message,
                "retry_scheduled_at": utcnow().isoformat(),
            }
            session.add(job)
        if document is not None:
            document.status = DocumentStatus.QUEUED.value
            session.add(document)
        session.commit()
    finally:
        session.close()


def mark_dead_letter(
    *,
    stage_name: str,
    job_id: str,
    document_id: str,
    tenant_id: str,
    error_message: str,
) -> None:
    session = SessionLocal()
    try:
        job = session.get(ProcessingJob, job_id)
        if job is not None:
            job.payload = {
                **job.payload,
                "dead_letter": {
                    "stage_name": stage_name,
                    "queue_name": settings.worker_dead_letter_queue,
                    "dead_lettered_at": utcnow().isoformat(),
                    "tenant_id": tenant_id,
                    "document_id": document_id,
                    "error_message": error_message,
                },
            }
            session.add(job)
            session.commit()
    finally:
        session.close()


def publish_dead_letter(
    *,
    stage_name: str,
    job_id: str,
    document_id: str,
    tenant_id: str,
    error_message: str,
) -> None:
    mark_dead_letter(
        stage_name=stage_name,
        job_id=job_id,
        document_id=document_id,
        tenant_id=tenant_id,
        error_message=error_message,
    )
    try:
        celery_app.send_task(
            DEAD_LETTER_TASK_NAME,
            kwargs={
                "stage_name": stage_name,
                "job_id": job_id,
                "document_id": document_id,
                "tenant_id": tenant_id,
                "error_message": error_message,
            },
            queue=settings.worker_dead_letter_queue,
        )
    except Exception:
        logger.exception(
            "Failed to publish dead-letter event",
            extra={"job_id": job_id, "document_id": document_id, "stage_name": stage_name},
        )


def execute_stage_task(
    self,
    *,
    stage_name: str,
    job_id: str,
    document_id: str,
    tenant_id: str,
    next_stage: str | None,
) -> dict:
    try:
        job, document = run_stage(stage_name, job_id, document_id)
        if next_stage is not None:
            enqueue_next_stage(current_job=job, document=document, next_stage=next_stage)
        return {"job_id": job_id, "document_id": document_id, "tenant_id": tenant_id}
    except Exception as exc:
        error_message = str(exc)
        retry_attempt = self.request.retries + 1
        if self.request.retries < settings.worker_task_max_retries:
            schedule_retry(
                stage_name=stage_name,
                job_id=job_id,
                document_id=document_id,
                error_message=(
                    f"Retry {retry_attempt}/{settings.worker_task_max_retries} scheduled: "
                    f"{error_message}"
                ),
            )
            raise self.retry(
                exc=exc,
                countdown=settings.worker_task_retry_delay_seconds,
                max_retries=settings.worker_task_max_retries,
            )

        publish_dead_letter(
            stage_name=stage_name,
            job_id=job_id,
            document_id=document_id,
            tenant_id=tenant_id,
            error_message=error_message,
        )
        raise


def run_stage(stage_name: str, job_id: str, document_id: str) -> tuple[ProcessingJob, Document]:
    session = SessionLocal()
    try:
        job = session.get(ProcessingJob, job_id)
        document = session.get(Document, document_id)
        if not job or not document:
            raise ValueError(f"Job or document missing for stage {stage_name}")

        job.status = JobStatus.RUNNING.value
        job.started_at = job.started_at or utcnow()
        job.attempts += 1
        document.status = DocumentStatus.PROCESSING.value
        session.add(job)
        session.add(document)
        session.commit()

        if stage_name == "document.parse":
            handle_parse_stage(session, document, job)
        elif stage_name == "document.chunk":
            handle_chunk_stage(session, document, job)
        elif stage_name == "document.embed":
            handle_embed_stage(session, document, job)
        elif stage_name == "graph.extract":
            handle_graph_extract_stage(session, document, job)
        elif stage_name == "graph.upsert":
            handle_graph_upsert_stage(session, document, job)

        job.status = JobStatus.COMPLETED.value
        job.completed_at = utcnow()
        session.add(job)

        next_stage = NEXT_STAGE[stage_name]
        if next_stage is None:
            document.status = DocumentStatus.PROCESSED.value
            session.add(document)
            session.commit()
            session.expunge(job)
            session.expunge(document)
            return job, document

        session.commit()
        session.expunge(job)
        session.expunge(document)
        return job, document
    except Exception as exc:
        session.rollback()
        job = session.get(ProcessingJob, job_id)
        document = session.get(Document, document_id)
        if job is not None:
            job.status = JobStatus.FAILED.value
            job.error_message = str(exc)
            job.completed_at = utcnow()
            session.add(job)
        if document is not None:
            document.status = DocumentStatus.FAILED.value
            session.add(document)
        session.commit()
        raise
    finally:
        session.close()


def handle_parse_stage(session, document: Document, job: ProcessingJob) -> None:
    version = get_current_version(session, document.id)
    raw_payload = storage_client.download_bytes(
        bucket_name=version.bucket_name,
        object_key=version.object_key,
    )
    canonical_document = build_canonical_document(
        document_id=document.id,
        document_version_id=version.id,
        tenant_id=document.tenant_id,
        title=document.title,
        file_name=document.file_name,
        content_type=document.content_type,
        payload=raw_payload,
    )
    parsed_object_key = str(
        PurePosixPath(document.tenant_id)
        / "documents"
        / document.id
        / version.version_label
        / "parsed"
        / "parsed.json"
    )
    stored = storage_client.upload_json(
        bucket_name=settings.rustfs_bucket_artifacts,
        object_key=parsed_object_key,
        payload=canonical_document.model_dump(mode="json"),
        metadata={"document_id": document.id, "artifact_type": "parsed_canonical_json"},
    )
    upsert_artifact(
        session=session,
        document_id=document.id,
        document_version_id=version.id,
        artifact_type="parsed_canonical_json",
        bucket_name=stored.bucket_name,
        object_key=stored.object_key,
        content_type="application/json",
    )
    job.payload = {
        **job.payload,
        "parsed_artifact_bucket": stored.bucket_name,
        "parsed_artifact_key": stored.object_key,
        "ocr_required": canonical_document.ocr_required,
        "ocr_applied": canonical_document.ocr_applied,
        "language": canonical_document.language,
    }
    session.add(job)


def handle_chunk_stage(session, document: Document, job: ProcessingJob) -> None:
    version = get_current_version(session, document.id)
    parsed_artifact = session.scalars(
        select(DocumentArtifact).where(
            DocumentArtifact.document_version_id == version.id,
            DocumentArtifact.artifact_type == "parsed_canonical_json",
        )
    ).first()
    if not parsed_artifact:
        raise ValueError(f"No parsed artifact found for document {document.id}")

    payload = storage_client.download_bytes(
        bucket_name=parsed_artifact.bucket_name,
        object_key=parsed_artifact.object_key,
    )
    canonical_document = CanonicalDocument.model_validate(json.loads(payload.decode("utf-8")))
    chunks = blocks_to_chunks(canonical_document)

    session.execute(
        delete(ChunkEmbedding).where(
            ChunkEmbedding.document_chunk_id.in_(
                select(DocumentChunk.id).where(DocumentChunk.document_version_id == version.id)
            )
        )
    )
    session.execute(delete(DocumentChunk).where(DocumentChunk.document_version_id == version.id))
    session.flush()

    chunk_rows: list[DocumentChunk] = []
    for chunk in chunks:
        chunk_row = DocumentChunk(
            id=chunk.id,
            document_id=chunk.document_id,
            document_version_id=chunk.document_version_id,
            tenant_id=chunk.tenant_id,
            chunk_index=chunk.chunk_index,
            section_name=chunk.section_name,
            page_start=chunk.page_start,
            page_end=chunk.page_end,
            content=chunk.content,
            token_estimate=chunk.token_estimate,
            content_hash=chunk_hash(chunk.content),
            chunk_metadata=chunk.metadata,
            )
        session.add(chunk_row)
        chunk_rows.append(chunk_row)

    chunks_object_key = str(
        PurePosixPath(document.tenant_id)
        / "documents"
        / document.id
        / version.version_label
        / "chunks"
        / "chunks.json"
    )
    stored = storage_client.upload_json(
        bucket_name=settings.rustfs_bucket_artifacts,
        object_key=chunks_object_key,
        payload=[chunk.model_dump(mode="json") for chunk in chunks],
        metadata={"document_id": document.id, "artifact_type": "chunks_json"},
    )
    upsert_artifact(
        session=session,
        document_id=document.id,
        document_version_id=version.id,
        artifact_type="chunks_json",
        bucket_name=stored.bucket_name,
        object_key=stored.object_key,
        content_type="application/json",
    )
    job.payload = {
        **job.payload,
        "chunk_count": len(chunk_rows),
        "chunks_artifact_bucket": stored.bucket_name,
        "chunks_artifact_key": stored.object_key,
    }
    session.add(job)


def handle_embed_stage(session, document: Document, job: ProcessingJob) -> None:
    version = get_current_version(session, document.id)
    chunk_rows = list(
        session.scalars(
            select(DocumentChunk)
            .where(DocumentChunk.document_version_id == version.id)
            .order_by(DocumentChunk.chunk_index.asc())
        ).all()
    )
    if not chunk_rows:
        raise ValueError(f"No chunks found for document {document.id}")

    vectors = embedding_provider.embed([chunk.content for chunk in chunk_rows])
    session.execute(
        delete(ChunkEmbedding).where(
            ChunkEmbedding.document_chunk_id.in_([chunk.id for chunk in chunk_rows])
        )
    )

    for chunk_row, vector in zip(chunk_rows, vectors, strict=True):
        session.add(
            ChunkEmbedding(
                document_chunk_id=chunk_row.id,
                model_name=settings.embedding_model_name,
                provider=embedding_provider.__class__.__name__,
                dimension=len(vector),
                embedding=vector,
            )
        )

    job.payload = {
        **job.payload,
        "embedding_count": len(chunk_rows),
        "embedding_provider": embedding_provider.__class__.__name__,
    }
    session.add(job)


def handle_graph_extract_stage(session, document: Document, job: ProcessingJob) -> None:
    version = get_current_version(session, document.id)
    chunk_rows = list(
        session.scalars(
            select(DocumentChunk)
            .where(DocumentChunk.document_version_id == version.id)
            .order_by(DocumentChunk.chunk_index.asc())
        ).all()
    )
    if not chunk_rows:
        raise ValueError(f"No chunks found for extraction on document {document.id}")

    extracted_payloads: list[ChunkExtractionPayload] = []
    session.execute(
        delete(ChunkExtraction).where(
            ChunkExtraction.document_chunk_id.in_([chunk.id for chunk in chunk_rows])
        )
    )
    session.flush()

    for chunk_row in chunk_rows:
        extraction = run_chunk_extraction(
            client=openrouter_client,
            model_name=settings.openrouter_model_extraction,
            tenant_id=document.tenant_id,
            document_id=document.id,
            chunk_id=chunk_row.id,
            content=chunk_row.content,
            section_name=chunk_row.section_name,
        )
        extracted_payloads.append(extraction)
        session.add(
            ChunkExtraction(
                document_chunk_id=chunk_row.id,
                model_name=settings.openrouter_model_extraction,
                provider="OpenRouter",
                extraction_json=extraction.model_dump(mode="json"),
            )
        )

    extraction_object_key = str(
        PurePosixPath(document.tenant_id)
        / "documents"
        / document.id
        / version.version_label
        / "extractions"
        / "chunk-extractions.json"
    )
    stored = storage_client.upload_json(
        bucket_name=settings.rustfs_bucket_artifacts,
        object_key=extraction_object_key,
        payload=[item.model_dump(mode="json") for item in extracted_payloads],
        metadata={"document_id": document.id, "artifact_type": "chunk_extractions_json"},
    )
    upsert_artifact(
        session=session,
        document_id=document.id,
        document_version_id=version.id,
        artifact_type="chunk_extractions_json",
        bucket_name=stored.bucket_name,
        object_key=stored.object_key,
        content_type="application/json",
    )
    job.payload = {
        **job.payload,
        "extraction_count": len(extracted_payloads),
        "extraction_model": settings.openrouter_model_extraction,
        "extractions_artifact_bucket": stored.bucket_name,
        "extractions_artifact_key": stored.object_key,
    }
    session.add(job)


def handle_graph_upsert_stage(session, document: Document, job: ProcessingJob) -> None:
    version = get_current_version(session, document.id)
    chunk_rows = list(
        session.scalars(
            select(DocumentChunk)
            .where(DocumentChunk.document_version_id == version.id)
            .order_by(DocumentChunk.chunk_index.asc())
        ).all()
    )
    if not chunk_rows:
        raise ValueError(f"No chunks found for graph upsert on document {document.id}")

    extraction_rows = list(
        session.scalars(
            select(ChunkExtraction).where(
                ChunkExtraction.document_chunk_id.in_([chunk.id for chunk in chunk_rows])
            )
        ).all()
    )
    if not extraction_rows:
        raise ValueError(f"No chunk extractions found for document {document.id}")

    neo4j_client.ensure_schema()
    clear_document_graph(client=neo4j_client, document_id=document.id)
    for row in extraction_rows:
        payload = ChunkExtractionPayload.model_validate(row.extraction_json)
        upsert_extraction_payload(
            client=neo4j_client,
            payload=payload,
            document_title=document.title,
        )

    job.payload = {
        **job.payload,
        "upserted_extraction_count": len(extraction_rows),
        "graph_backend": "neo4j",
    }
    session.add(job)


@celery_app.task(name="document.parse", bind=True)
def document_parse(self, job_id: str, document_id: str, tenant_id: str) -> dict:
    return execute_stage_task(
        self,
        stage_name="document.parse",
        job_id=job_id,
        document_id=document_id,
        tenant_id=tenant_id,
        next_stage="document.chunk",
    )


@celery_app.task(name="document.chunk", bind=True)
def document_chunk(self, job_id: str, document_id: str, tenant_id: str) -> dict:
    return execute_stage_task(
        self,
        stage_name="document.chunk",
        job_id=job_id,
        document_id=document_id,
        tenant_id=tenant_id,
        next_stage="document.embed",
    )


@celery_app.task(name="document.embed", bind=True)
def document_embed(self, job_id: str, document_id: str, tenant_id: str) -> dict:
    return execute_stage_task(
        self,
        stage_name="document.embed",
        job_id=job_id,
        document_id=document_id,
        tenant_id=tenant_id,
        next_stage="graph.extract",
    )


@celery_app.task(name="graph.extract", bind=True)
def graph_extract(self, job_id: str, document_id: str, tenant_id: str) -> dict:
    return execute_stage_task(
        self,
        stage_name="graph.extract",
        job_id=job_id,
        document_id=document_id,
        tenant_id=tenant_id,
        next_stage="graph.upsert",
    )


@celery_app.task(name="graph.upsert", bind=True)
def graph_upsert(self, job_id: str, document_id: str, tenant_id: str) -> dict:
    return execute_stage_task(
        self,
        stage_name="graph.upsert",
        job_id=job_id,
        document_id=document_id,
        tenant_id=tenant_id,
        next_stage=None,
    )


@celery_app.task(name=DEAD_LETTER_TASK_NAME, bind=True)
def document_dead_letter(
    self,
    stage_name: str,
    job_id: str,
    document_id: str,
    tenant_id: str,
    error_message: str,
) -> dict:
    logger.error(
        "Dead-lettered processing job",
        extra={
            "stage_name": stage_name,
            "job_id": job_id,
            "document_id": document_id,
            "tenant_id": tenant_id,
            "error_message": error_message,
        },
    )
    return {
        "stage_name": stage_name,
        "job_id": job_id,
        "document_id": document_id,
        "tenant_id": tenant_id,
        "error_message": error_message,
    }
