import json
from datetime import datetime, timezone
from pathlib import PurePosixPath

from sqlalchemy import delete, select

from enterprise_ai_core.chunking import blocks_to_chunks, chunk_hash
from enterprise_ai_core.config import get_settings
from enterprise_ai_core.db import SessionLocal
from enterprise_ai_core.embedding import get_embedding_provider
from enterprise_ai_core.extraction import clone_extraction_for_chunk, run_parallel_chunk_extractions
from enterprise_ai_core.graph_upsert import clear_document_graph, upsert_extraction_payload
from enterprise_ai_core.graphdb import get_neo4j_client
from enterprise_ai_core.logging import get_logger
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
from enterprise_ai_core.progress import build_job_progress_snapshot
from enterprise_ai_core.queue import get_celery_app
from enterprise_ai_core.schemas import CanonicalDocument, ChunkExtractionPayload, DocumentStatus, JobStatus
from enterprise_ai_core.storage import RustFSStorageClient

celery_app = get_celery_app()
settings = get_settings()
storage_client = RustFSStorageClient()
embedding_provider = get_embedding_provider()
openrouter_client = OpenRouterClient()
neo4j_client = get_neo4j_client()
logger = get_logger(__name__)

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


class StaleTaskError(Exception):
    """Raised when a broker task no longer has backing DB state."""


def get_target_version(session, document_id: str, job: ProcessingJob) -> DocumentVersion:
    version_id = job.payload.get("document_version_id")
    if version_id:
        version = session.get(DocumentVersion, version_id)
        if version and version.document_id == document_id:
            return version

    version = session.scalars(
        select(DocumentVersion)
        .where(DocumentVersion.document_id == document_id)
        .order_by(DocumentVersion.version_number.desc(), DocumentVersion.created_at.desc())
    ).first()
    if not version:
        raise ValueError(f"No document version found for document {document_id}")
    job.payload = {**job.payload, "document_version_id": version.id, "version_label": version.version_label}
    session.add(job)
    session.flush()
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
    artifact_metadata: dict | None = None,
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
        artifact.artifact_metadata = artifact_metadata or artifact.artifact_metadata
        session.add(artifact)
        return artifact

    artifact = DocumentArtifact(
        document_id=document_id,
        document_version_id=document_version_id,
        artifact_type=artifact_type,
        bucket_name=bucket_name,
        object_key=object_key,
        content_type=content_type,
        artifact_metadata=artifact_metadata or {},
    )
    session.add(artifact)
    return artifact


def propagate_job_payload(current_job: ProcessingJob) -> dict:
    propagated_keys = [
        "document_version_id",
        "version_label",
        "processing_mode",
        "reprocess_reason",
        "chunk_ids_requiring_embedding",
        "chunk_ids_requiring_extraction",
        "chunk_count",
        "chunk_delta",
        "parse_quality_score",
    ]
    propagated = {key: current_job.payload[key] for key in propagated_keys if key in current_job.payload}
    propagated["previous_job_id"] = current_job.id
    return propagated


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
            payload=propagate_job_payload(current_job),
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
            logger.info(
                "next_stage_enqueued",
                tenant_id=document.tenant_id,
                document_id=document.id,
                current_job_id=current_job.id,
                next_job_id=next_job.id,
                next_stage=next_stage,
                queue_name=next_stage,
            )
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
        if job is None:
            return
        version = get_target_version(session, document_id, job)
        job.status = JobStatus.QUEUED.value
        job.error_message = error_message
        job.completed_at = None
        job.payload = {
            **job.payload,
            "last_retry_error": error_message,
            "retry_scheduled_at": utcnow().isoformat(),
            "retry_stage_name": stage_name,
        }
        version.status = DocumentStatus.QUEUED.value
        session.add(job)
        session.add(version)
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
        document = session.get(Document, document_id)
        if document is not None:
            document.status = DocumentStatus.FAILED.value
            session.add(document)
        if job is not None:
            version = get_target_version(session, document_id, job)
            version.status = DocumentStatus.FAILED.value
            session.add(version)
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
    except StaleTaskError as exc:
        logger.warning(
            "stale_task_skipped",
            stage_name=stage_name,
            job_id=job_id,
            document_id=document_id,
            tenant_id=tenant_id,
            reason=str(exc),
        )
        return {
            "job_id": job_id,
            "document_id": document_id,
            "tenant_id": tenant_id,
            "skipped": True,
            "reason": str(exc),
        }
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
            raise StaleTaskError(f"Job or document missing for stage {stage_name}")

        version = get_target_version(session, document.id, job)
        job.status = JobStatus.RUNNING.value
        job.started_at = job.started_at or utcnow()
        job.attempts += 1
        document.status = DocumentStatus.PROCESSING.value
        version.status = DocumentStatus.PROCESSING.value
        session.add(job)
        session.add(document)
        session.add(version)
        session.commit()
        logger.info(
            "stage_started",
            stage_name=stage_name,
            job_id=job.id,
            document_id=document.id,
            tenant_id=document.tenant_id,
            version_label=version.version_label,
            processing_mode=str(job.payload.get("processing_mode", "full")),
        )

        if stage_name == "document.parse":
            handle_parse_stage(session, document, version, job)
        elif stage_name == "document.chunk":
            handle_chunk_stage(session, document, version, job)
        elif stage_name == "document.embed":
            handle_embed_stage(session, document, version, job)
        elif stage_name == "graph.extract":
            handle_graph_extract_stage(session, document, version, job)
        elif stage_name == "graph.upsert":
            handle_graph_upsert_stage(session, document, version, job)

        job.status = JobStatus.COMPLETED.value
        job.completed_at = utcnow()
        session.add(job)
        progress_snapshot = build_job_progress_snapshot(job)
        logger.info(
            "document_pipeline_checkpoint",
            stage_name=stage_name,
            job_id=job.id,
            document_id=document.id,
            tenant_id=document.tenant_id,
            version_label=version.version_label,
            progress_percent=progress_snapshot.progress_percent,
            progress_label=progress_snapshot.progress_label,
            progress_detail=progress_snapshot.progress_detail,
            processing_mode=progress_snapshot.processing_mode,
        )

        next_stage = NEXT_STAGE[stage_name]
        if next_stage is None:
            document.status = DocumentStatus.PROCESSED.value
            version.status = DocumentStatus.PROCESSED.value
            session.add(document)
            session.add(version)
            session.commit()
            logger.info(
                "stage_completed",
                stage_name=stage_name,
                job_id=job.id,
                document_id=document.id,
                tenant_id=document.tenant_id,
                version_label=version.version_label,
                document_status=document.status,
                version_status=version.status,
            )
            session.expunge(job)
            session.expunge(document)
            return job, document

        session.commit()
        logger.info(
            "stage_completed",
            stage_name=stage_name,
            job_id=job.id,
            document_id=document.id,
            tenant_id=document.tenant_id,
            version_label=version.version_label,
            next_stage=next_stage,
        )
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
            version = get_target_version(session, document_id, job)
            version.status = DocumentStatus.FAILED.value
            session.add(version)
        if document is not None:
            document.status = DocumentStatus.FAILED.value
            session.add(document)
        session.commit()
        logger.exception(
            "stage_failed",
            stage_name=stage_name,
            job_id=job_id,
            document_id=document_id,
            tenant_id=document.tenant_id if document is not None else None,
            error_message=str(exc),
        )
        raise
    finally:
        session.close()


def handle_parse_stage(
    session,
    document: Document,
    version: DocumentVersion,
    job: ProcessingJob,
) -> None:
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
    base_path = (
        PurePosixPath(document.tenant_id)
        / "documents"
        / document.id
        / version.version_label
    )
    parsed_object_key = str(base_path / "parsed" / "parsed.json")
    parsed_stored = storage_client.upload_json(
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
        bucket_name=parsed_stored.bucket_name,
        object_key=parsed_stored.object_key,
        content_type="application/json",
        artifact_metadata={
            "version_label": version.version_label,
            "parse_quality_score": canonical_document.parse_quality_score,
        },
    )

    parse_report = {
        "document_id": document.id,
        "document_version_id": version.id,
        "version_label": version.version_label,
        "parse_quality_score": canonical_document.parse_quality_score,
        "parse_warnings": canonical_document.parse_warnings,
        "ocr_required": canonical_document.ocr_required,
        "ocr_applied": canonical_document.ocr_applied,
        "language": canonical_document.language,
        "block_count": len(canonical_document.blocks),
        "metadata": canonical_document.metadata,
    }
    report_object_key = str(base_path / "parsed" / "parse-report.json")
    report_stored = storage_client.upload_json(
        bucket_name=settings.rustfs_bucket_artifacts,
        object_key=report_object_key,
        payload=parse_report,
        metadata={"document_id": document.id, "artifact_type": "parse_report_json"},
    )
    upsert_artifact(
        session=session,
        document_id=document.id,
        document_version_id=version.id,
        artifact_type="parse_report_json",
        bucket_name=report_stored.bucket_name,
        object_key=report_stored.object_key,
        content_type="application/json",
        artifact_metadata={"version_label": version.version_label},
    )
    version.parse_quality_score = canonical_document.parse_quality_score
    session.add(version)
    job.payload = {
        **job.payload,
        "parsed_artifact_bucket": parsed_stored.bucket_name,
        "parsed_artifact_key": parsed_stored.object_key,
        "parse_report_bucket": report_stored.bucket_name,
        "parse_report_key": report_stored.object_key,
        "ocr_required": canonical_document.ocr_required,
        "ocr_applied": canonical_document.ocr_applied,
        "language": canonical_document.language,
        "parse_quality_score": canonical_document.parse_quality_score,
    }
    session.add(job)
    logger.info(
        "parse_completed",
        stage_name="document.parse",
        job_id=job.id,
        document_id=document.id,
        tenant_id=document.tenant_id,
        version_label=version.version_label,
        block_count=len(canonical_document.blocks),
        parse_quality_score=canonical_document.parse_quality_score,
        ocr_required=canonical_document.ocr_required,
        ocr_applied=canonical_document.ocr_applied,
        language=canonical_document.language,
        warning_count=len(canonical_document.parse_warnings),
    )


def handle_chunk_stage(
    session,
    document: Document,
    version: DocumentVersion,
    job: ProcessingJob,
) -> None:
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
    existing_chunk_rows = list(
        session.scalars(
            select(DocumentChunk)
            .where(DocumentChunk.document_version_id == version.id)
            .order_by(DocumentChunk.chunk_index.asc())
        ).all()
    )
    existing_by_hash: dict[str, list[DocumentChunk]] = {}
    for row in existing_chunk_rows:
        existing_by_hash.setdefault(row.content_hash, []).append(row)

    retained_ids: set[str] = set()
    reused_chunk_ids: list[str] = []
    changed_chunk_ids: list[str] = []
    processing_mode = str(job.payload.get("processing_mode", "full"))

    for chunk in chunks:
        content_digest = chunk_hash(chunk.content)
        reusable = next(
            (
                candidate
                for candidate in existing_by_hash.get(content_digest, [])
                if candidate.id not in retained_ids
            ),
            None,
        )
        if reusable is not None:
            reusable.chunk_index = chunk.chunk_index
            reusable.section_name = chunk.section_name
            reusable.page_start = chunk.page_start
            reusable.page_end = chunk.page_end
            reusable.source_offset_start = chunk.source_offset_start
            reusable.source_offset_end = chunk.source_offset_end
            reusable.heading_path = chunk.heading_path
            reusable.content = chunk.content
            reusable.token_estimate = chunk.token_estimate
            reusable.content_hash = content_digest
            reusable.parse_quality_score = chunk.parse_quality_score
            reusable.chunk_metadata = chunk.metadata
            session.add(reusable)
            retained_ids.add(reusable.id)
            reused_chunk_ids.append(reusable.id)
            continue

        row = DocumentChunk(
            id=chunk.id,
            document_id=chunk.document_id,
            document_version_id=chunk.document_version_id,
            tenant_id=chunk.tenant_id,
            chunk_index=chunk.chunk_index,
            section_name=chunk.section_name,
            page_start=chunk.page_start,
            page_end=chunk.page_end,
            source_offset_start=chunk.source_offset_start,
            source_offset_end=chunk.source_offset_end,
            heading_path=chunk.heading_path,
            content=chunk.content,
            token_estimate=chunk.token_estimate,
            content_hash=content_digest,
            parse_quality_score=chunk.parse_quality_score,
            chunk_metadata=chunk.metadata,
        )
        session.add(row)
        retained_ids.add(row.id)
        changed_chunk_ids.append(row.id)

    obsolete_ids = [row.id for row in existing_chunk_rows if row.id not in retained_ids]
    if obsolete_ids:
        session.execute(delete(ChunkEmbedding).where(ChunkEmbedding.document_chunk_id.in_(obsolete_ids)))
        session.execute(delete(ChunkExtraction).where(ChunkExtraction.document_chunk_id.in_(obsolete_ids)))
        session.execute(delete(DocumentChunk).where(DocumentChunk.id.in_(obsolete_ids)))

    if processing_mode == "full":
        reprocess_ids = list(retained_ids)
        if reprocess_ids:
            session.execute(
                delete(ChunkEmbedding).where(ChunkEmbedding.document_chunk_id.in_(reprocess_ids))
            )
            session.execute(
                delete(ChunkExtraction).where(ChunkExtraction.document_chunk_id.in_(reprocess_ids))
            )
        chunk_ids_requiring_embedding = reprocess_ids
        chunk_ids_requiring_extraction = reprocess_ids
    else:
        chunk_ids_requiring_embedding = changed_chunk_ids
        chunk_ids_requiring_extraction = changed_chunk_ids

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
        artifact_metadata={"version_label": version.version_label, "chunk_count": len(chunks)},
    )
    job.payload = {
        **job.payload,
        "chunk_count": len(chunks),
        "chunks_artifact_bucket": stored.bucket_name,
        "chunks_artifact_key": stored.object_key,
        "chunk_ids_requiring_embedding": chunk_ids_requiring_embedding,
        "chunk_ids_requiring_extraction": chunk_ids_requiring_extraction,
        "chunk_delta": {
            "new_or_changed": len(changed_chunk_ids),
            "reused": len(reused_chunk_ids),
            "removed": len(obsolete_ids),
        },
    }
    session.add(job)
    logger.info(
        "chunk_completed",
        stage_name="document.chunk",
        job_id=job.id,
        document_id=document.id,
        tenant_id=document.tenant_id,
        version_label=version.version_label,
        processing_mode=processing_mode,
        chunk_count=len(chunks),
        new_or_changed=len(changed_chunk_ids),
        reused=len(reused_chunk_ids),
        removed=len(obsolete_ids),
        embedding_targets=len(chunk_ids_requiring_embedding),
        extraction_targets=len(chunk_ids_requiring_extraction),
    )


def handle_embed_stage(
    session,
    document: Document,
    version: DocumentVersion,
    job: ProcessingJob,
) -> None:
    chunk_ids = list(job.payload.get("chunk_ids_requiring_embedding", []))
    if not chunk_ids and str(job.payload.get("processing_mode", "full")) != "full":
        job.payload = {**job.payload, "embedding_count": 0, "embedding_skipped": True}
        session.add(job)
        logger.info(
            "embedding_skipped",
            stage_name="document.embed",
            job_id=job.id,
            document_id=document.id,
            tenant_id=document.tenant_id,
            version_label=version.version_label,
            reason="no_chunk_ids_for_incremental_mode",
        )
        return

    statement = (
        select(DocumentChunk)
        .where(DocumentChunk.document_version_id == version.id)
        .order_by(DocumentChunk.chunk_index.asc())
    )
    if chunk_ids:
        statement = statement.where(DocumentChunk.id.in_(chunk_ids))
    chunk_rows = list(session.scalars(statement).all())
    if not chunk_rows:
        job.payload = {**job.payload, "embedding_count": 0, "embedding_skipped": True}
        session.add(job)
        logger.info(
            "embedding_skipped",
            stage_name="document.embed",
            job_id=job.id,
            document_id=document.id,
            tenant_id=document.tenant_id,
            version_label=version.version_label,
            reason="no_chunk_rows_selected",
        )
        return

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
    logger.info(
        "embedding_completed",
        stage_name="document.embed",
        job_id=job.id,
        document_id=document.id,
        tenant_id=document.tenant_id,
        version_label=version.version_label,
        embedding_count=len(chunk_rows),
        embedding_provider=embedding_provider.__class__.__name__,
        embedding_model=settings.embedding_model_name,
        embedding_dimension=len(vectors[0]) if vectors else 0,
    )


def handle_graph_extract_stage(
    session,
    document: Document,
    version: DocumentVersion,
    job: ProcessingJob,
) -> None:
    chunk_ids = list(job.payload.get("chunk_ids_requiring_extraction", []))
    if not chunk_ids and str(job.payload.get("processing_mode", "full")) != "full":
        job.payload = {**job.payload, "extraction_count": 0, "extraction_skipped": True}
        session.add(job)
        logger.info(
            "graph_extract_skipped",
            stage_name="graph.extract",
            job_id=job.id,
            document_id=document.id,
            tenant_id=document.tenant_id,
            version_label=version.version_label,
            reason="no_chunk_ids_for_incremental_mode",
        )
        return

    statement = (
        select(DocumentChunk)
        .where(DocumentChunk.document_version_id == version.id)
        .order_by(DocumentChunk.chunk_index.asc())
    )
    if chunk_ids:
        statement = statement.where(DocumentChunk.id.in_(chunk_ids))
    chunk_rows = list(session.scalars(statement).all())
    if not chunk_rows:
        job.payload = {**job.payload, "extraction_count": 0, "extraction_skipped": True}
        session.add(job)
        logger.info(
            "graph_extract_skipped",
            stage_name="graph.extract",
            job_id=job.id,
            document_id=document.id,
            tenant_id=document.tenant_id,
            version_label=version.version_label,
            reason="no_chunk_rows_selected",
        )
        return

    extracted_payloads: list[ChunkExtractionPayload] = []
    session.execute(
        delete(ChunkExtraction).where(ChunkExtraction.document_chunk_id.in_([chunk.id for chunk in chunk_rows]))
    )
    session.flush()

    chunk_groups: dict[str, list[DocumentChunk]] = {}
    for chunk_row in chunk_rows:
        chunk_groups.setdefault(chunk_row.content_hash, []).append(chunk_row)

    unique_chunk_requests: list[dict[str, str]] = []
    chunk_group_by_request_id: dict[str, list[DocumentChunk]] = {}
    for group in chunk_groups.values():
        representative = group[0]
        unique_chunk_requests.append(
            {
                "chunk_id": representative.id,
                "content": representative.content,
                "section_name": representative.section_name,
            }
        )
        chunk_group_by_request_id[representative.id] = group
    progress_interval = max(1, settings.graph_extract_progress_log_interval)
    commit_interval = max(1, settings.graph_extract_commit_interval)
    completed_chunk_count = 0
    logger.info(
        "graph_extract_initialized",
        stage_name="graph.extract",
        job_id=job.id,
        document_id=document.id,
        tenant_id=document.tenant_id,
        version_label=version.version_label,
        total_chunks=len(chunk_rows),
        unique_chunk_count=len(unique_chunk_requests),
        reused_chunk_count=len(chunk_rows) - len(unique_chunk_requests),
        max_concurrency=settings.graph_extract_max_concurrency,
        commit_interval=commit_interval,
        progress_log_interval=progress_interval,
    )

    def log_extract_progress(completed: int, total: int) -> None:
        if completed == total or completed % progress_interval == 0:
            logger.info(
                "graph_extract_progress",
                stage_name="graph.extract",
                job_id=job.id,
                document_id=document.id,
                tenant_id=document.tenant_id,
                version_label=version.version_label,
                completed_unique_chunks=completed,
                total_unique_chunks=total,
                total_chunks=len(chunk_rows),
            )

    def persist_extraction_progress(
        payload: ChunkExtractionPayload,
        completed_unique_chunks: int,
        total_unique_chunks: int,
    ) -> None:
        nonlocal completed_chunk_count

        grouped_rows = chunk_group_by_request_id.get(payload.document_chunk_id)
        if grouped_rows is None:
            raise KeyError(
                f"Missing chunk group for extraction payload {payload.document_chunk_id}"
            )
        for chunk_row in grouped_rows:
            extraction = (
                payload
                if chunk_row.id == payload.document_chunk_id
                else clone_extraction_for_chunk(payload, chunk_id=chunk_row.id)
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
        completed_chunk_count += len(grouped_rows)
        job.payload = {
            **job.payload,
            "extraction_completed_unique_chunks": completed_unique_chunks,
            "extraction_total_unique_chunks": total_unique_chunks,
            "extraction_completed_chunks": completed_chunk_count,
            "extraction_total_chunks": len(chunk_rows),
        }
        session.add(job)
        if (
            completed_unique_chunks == total_unique_chunks
            or completed_unique_chunks % commit_interval == 0
        ):
            session.commit()
            logger.info(
                "graph_extract_batch_committed",
                stage_name="graph.extract",
                job_id=job.id,
                document_id=document.id,
                tenant_id=document.tenant_id,
                version_label=version.version_label,
                completed_unique_chunks=completed_unique_chunks,
                total_unique_chunks=total_unique_chunks,
                completed_chunks=completed_chunk_count,
                total_chunks=len(chunk_rows),
            )

    unique_extractions = run_parallel_chunk_extractions(
        client=openrouter_client,
        model_name=settings.openrouter_model_extraction,
        tenant_id=document.tenant_id,
        document_id=document.id,
        chunk_requests=unique_chunk_requests,
        progress_callback=log_extract_progress,
        result_callback=persist_extraction_progress,
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
        artifact_metadata={"version_label": version.version_label},
    )
    job.payload = {
        **job.payload,
        "extraction_count": len(extracted_payloads),
        "extraction_unique_chunk_count": len(unique_chunk_requests),
        "extraction_reused_chunk_count": len(chunk_rows) - len(unique_chunk_requests),
        "extraction_model": settings.openrouter_model_extraction,
        "extractions_artifact_bucket": stored.bucket_name,
        "extractions_artifact_key": stored.object_key,
    }
    session.add(job)
    logger.info(
        "graph_extract_completed",
        stage_name="graph.extract",
        job_id=job.id,
        document_id=document.id,
        tenant_id=document.tenant_id,
        version_label=version.version_label,
        extraction_count=len(extracted_payloads),
        unique_chunk_count=len(unique_extractions),
        reused_chunk_count=len(chunk_rows) - len(unique_chunk_requests),
        max_concurrency=settings.graph_extract_max_concurrency,
        extraction_model=settings.openrouter_model_extraction,
    )


def handle_graph_upsert_stage(
    session,
    document: Document,
    version: DocumentVersion,
    job: ProcessingJob,
) -> None:
    if not version.is_current or document.version != version.version_label:
        job.payload = {
            **job.payload,
            "graph_sync_skipped": True,
            "graph_sync_skip_reason": "target_version_is_not_current",
        }
        session.add(job)
        logger.info(
            "graph_upsert_skipped",
            stage_name="graph.upsert",
            job_id=job.id,
            document_id=document.id,
            tenant_id=document.tenant_id,
            version_label=version.version_label,
            reason="target_version_is_not_current",
        )
        return

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
    clear_document_graph(
        client=neo4j_client,
        document_id=document.id,
        tenant_id=document.tenant_id,
    )
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
        "graph_version_label": version.version_label,
    }
    session.add(job)
    logger.info(
        "graph_upsert_completed",
        stage_name="graph.upsert",
        job_id=job.id,
        document_id=document.id,
        tenant_id=document.tenant_id,
        version_label=version.version_label,
        upserted_extraction_count=len(extraction_rows),
        graph_backend="neo4j",
    )


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
