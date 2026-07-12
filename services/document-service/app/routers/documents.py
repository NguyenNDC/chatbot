import hashlib
import json
from datetime import datetime, timezone
from pathlib import PurePosixPath
from uuid import uuid4

from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from enterprise_ai_core.config import get_settings
from enterprise_ai_core.db import get_db_session
from enterprise_ai_core.graph_upsert import clear_document_graph
from enterprise_ai_core.graphdb import get_neo4j_client
from enterprise_ai_core.models import (
    ChunkEmbedding,
    ChunkExtraction,
    Document,
    DocumentArtifact,
    DocumentChunk,
    DocumentVersion,
    ProcessingJob,
    Tenant,
)
from enterprise_ai_core.progress import build_document_progress_snapshot, build_job_progress_snapshot
from enterprise_ai_core.queue import get_celery_app
from enterprise_ai_core.schemas import (
    DocumentChunkPreviewItem,
    DocumentChunkPreviewResponse,
    DocumentDeleteResponse,
    DocumentItem,
    DocumentListResponse,
    DocumentParsedPreviewResponse,
    DocumentReprocessRequest,
    DocumentStatus,
    DocumentVersionItem,
    DocumentVersionListResponse,
    JobStatus,
    ProcessingJobItem,
    UploadAcceptedResponse,
)
from enterprise_ai_core.storage import RustFSStorageClient

router = APIRouter(tags=["documents"])
settings = get_settings()
storage_client = RustFSStorageClient()
celery_app = get_celery_app()
neo4j_client = get_neo4j_client()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def build_processing_job_item(job: ProcessingJob) -> ProcessingJobItem:
    snapshot = build_job_progress_snapshot(job)
    return ProcessingJobItem(
        id=job.id,
        tenant_id=job.tenant_id,
        document_id=job.document_id,
        job_type=job.job_type,
        queue_name=job.queue_name,
        status=JobStatus(job.status),
        celery_task_id=job.celery_task_id,
        attempts=job.attempts,
        error_message=job.error_message,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        parent_job_id=job.parent_job_id,
        stage_label=snapshot.stage_label,
        version_label=snapshot.version_label,
        processing_mode=snapshot.processing_mode,
        progress_percent=snapshot.progress_percent,
        progress_current=snapshot.progress_current,
        progress_total=snapshot.progress_total,
        progress_label=snapshot.progress_label,
        progress_detail=snapshot.progress_detail,
    )


def build_document_item(
    document: Document,
    jobs: list[ProcessingJob],
    current_version: DocumentVersion | None,
) -> DocumentItem:
    progress = build_document_progress_snapshot(
        document_status=document.status,
        jobs=jobs,
        current_version_id=current_version.id if current_version else None,
    )
    current_job = progress.selected_job
    return DocumentItem(
        id=document.id,
        tenant_id=document.tenant_id,
        title=document.title,
        file_name=document.file_name,
        content_type=document.content_type,
        status=DocumentStatus(document.status),
        version=document.version,
        tags=document.tags,
        source=document.source,
        checksum_sha256=document.checksum_sha256,
        size_bytes=document.size_bytes,
        current_job_id=current_job.id if current_job else None,
        current_job_type=current_job.job_type if current_job else None,
        current_job_status=JobStatus(current_job.status) if current_job else None,
        current_job_error_message=current_job.error_message if current_job else None,
        processing_stage=progress.stage,
        processing_stage_label=progress.stage_label,
        processing_stage_status=JobStatus(progress.stage_status) if progress.stage_status else None,
        processing_progress_percent=progress.progress_percent,
        processing_progress_current=progress.progress_current,
        processing_progress_total=progress.progress_total,
        processing_progress_label=progress.progress_label,
        processing_progress_detail=progress.progress_detail,
        processing_mode=progress.processing_mode,
        created_at=document.created_at,
    )


def build_version_item(version: DocumentVersion) -> DocumentVersionItem:
    return DocumentVersionItem.model_validate(version)


def latest_job_for_document(db: Session, document_id: str) -> ProcessingJob | None:
    statement = (
        select(ProcessingJob)
        .where(ProcessingJob.document_id == document_id)
        .order_by(ProcessingJob.created_at.desc())
    )
    return db.scalars(statement).first()


def get_document_for_tenant(db: Session, document_id: str, tenant_id: str) -> Document | None:
    statement = select(Document).where(Document.id == document_id, Document.tenant_id == tenant_id)
    return db.scalars(statement).first()


def get_active_tenant(db: Session, tenant_id: str) -> Tenant:
    tenant = db.get(Tenant, tenant_id)
    if tenant is None or tenant.status != "active":
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant


def current_version_for_document(db: Session, document_id: str) -> DocumentVersion | None:
    statement = (
        select(DocumentVersion)
        .where(DocumentVersion.document_id == document_id, DocumentVersion.is_current.is_(True))
        .order_by(DocumentVersion.version_number.desc())
    )
    version = db.scalars(statement).first()
    if version is not None:
        return version
    return latest_version_for_document(db, document_id)


def latest_version_for_document(db: Session, document_id: str) -> DocumentVersion | None:
    statement = (
        select(DocumentVersion)
        .where(DocumentVersion.document_id == document_id)
        .order_by(DocumentVersion.version_number.desc(), DocumentVersion.created_at.desc())
    )
    return db.scalars(statement).first()


def artifact_for_version(
    db: Session,
    *,
    document_version_id: str,
    artifact_type: str,
) -> DocumentArtifact | None:
    statement = (
        select(DocumentArtifact)
        .where(
            DocumentArtifact.document_version_id == document_version_id,
            DocumentArtifact.artifact_type == artifact_type,
        )
        .order_by(DocumentArtifact.created_at.desc())
    )
    return db.scalars(statement).first()


def next_version_info(db: Session, document_id: str) -> tuple[int, str, str | None]:
    latest_version = latest_version_for_document(db, document_id)
    next_number = (latest_version.version_number + 1) if latest_version else 1
    return next_number, f"v{next_number}", latest_version.id if latest_version else None


def parse_effective_from(raw_value: str | None) -> datetime:
    if not raw_value:
        return utcnow()
    normalized = raw_value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid effective_from datetime") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def safe_delete_object(*, bucket_name: str, object_key: str) -> None:
    try:
        storage_client.delete_object(bucket_name=bucket_name, object_key=object_key)
    except ClientError:
        # Missing or already-deleted objects should not block cleanup.
        pass


def safe_revoke_task(task_id: str | None) -> None:
    if not task_id:
        return
    try:
        celery_app.control.revoke(task_id, terminate=False)
    except Exception:
        # Best-effort revoke only. Cleanup should still continue.
        pass


def enqueue_root_job(
    db: Session,
    *,
    root_job: ProcessingJob,
    document: Document,
    tenant_id: str,
) -> None:
    try:
        task = celery_app.send_task(
            "document.parse",
            kwargs={"job_id": root_job.id, "document_id": document.id, "tenant_id": tenant_id},
            queue="document.parse",
        )
        root_job.celery_task_id = task.id
        db.add(root_job)
        db.commit()
        db.refresh(root_job)
    except Exception as exc:
        db.rollback()
        root_job.status = JobStatus.FAILED.value
        root_job.error_message = f"Failed to enqueue root job: {exc}"
        document.status = DocumentStatus.FAILED.value
        db.add(root_job)
        db.add(document)
        db.commit()
        raise HTTPException(status_code=502, detail="Upload persisted but queue publish failed") from exc


def persist_version_upload(
    db: Session,
    *,
    document: Document,
    tenant_id: str,
    title: str,
    tags: list[str],
    upload_file: UploadFile,
    payload: bytes,
    effective_from: datetime,
) -> tuple[DocumentVersion, ProcessingJob]:
    checksum_sha256 = hashlib.sha256(payload).hexdigest()
    for version in document.versions:
        if version.checksum_sha256 == checksum_sha256:
            existing_job = latest_job_for_document(db, document.id)
            if not existing_job:
                raise HTTPException(status_code=409, detail="Duplicate document version exists without job")
            raise HTTPException(
                status_code=409,
                detail={
                    "document_id": document.id,
                    "document_version_id": version.id,
                    "message": "Duplicate version checksum already exists",
                },
            )

    version_number, version_label, parent_version_id = next_version_info(db, document.id)
    file_name = upload_file.filename or document.file_name or "upload.bin"
    object_key = str(
        PurePosixPath(tenant_id) / "documents" / document.id / version_label / "raw" / file_name
    )

    stored_object = storage_client.upload_bytes(
        bucket_name=settings.rustfs_bucket_raw,
        object_key=object_key,
        payload=payload,
        content_type=upload_file.content_type or "application/octet-stream",
        metadata={"tenant_id": tenant_id, "document_id": document.id, "version_label": version_label},
    )

    current_version = current_version_for_document(db, document.id)
    if current_version is not None:
        current_version.is_current = False
        current_version.effective_to = effective_from
        db.add(current_version)

    document_version_id = str(uuid4())
    version = DocumentVersion(
        id=document_version_id,
        document_id=document.id,
        parent_version_id=parent_version_id,
        version_label=version_label,
        version_number=version_number,
        object_key=stored_object.object_key,
        bucket_name=stored_object.bucket_name,
        checksum_sha256=checksum_sha256,
        size_bytes=len(payload),
        status=DocumentStatus.QUEUED.value,
        processing_scope="full",
        is_current=True,
        effective_from=effective_from,
    )
    artifact = DocumentArtifact(
        document_id=document.id,
        document_version_id=document_version_id,
        artifact_type="raw_upload",
        bucket_name=stored_object.bucket_name,
        object_key=stored_object.object_key,
        content_type=upload_file.content_type or "application/octet-stream",
        artifact_metadata={"version_label": version_label, "checksum_sha256": checksum_sha256},
    )

    document.title = title
    document.file_name = file_name
    document.content_type = upload_file.content_type or "application/octet-stream"
    document.status = DocumentStatus.QUEUED.value
    document.version = version_label
    document.tags = tags
    document.source = "rustfs"
    document.checksum_sha256 = checksum_sha256
    document.size_bytes = len(payload)
    db.add(document)
    db.add(version)
    db.add(artifact)
    db.flush()

    root_job = ProcessingJob(
        tenant_id=tenant_id,
        document_id=document.id,
        job_type="document.parse",
        queue_name="document.parse",
        status=JobStatus.QUEUED.value,
        payload={
            "bucket_name": stored_object.bucket_name,
            "object_key": stored_object.object_key,
            "file_name": file_name,
            "document_version_id": version.id,
            "version_label": version_label,
            "processing_mode": "full",
        },
    )
    db.add(root_job)
    db.commit()
    db.refresh(version)
    db.refresh(root_job)
    db.refresh(document)
    return version, root_job


def create_root_document(
    *,
    tenant_id: str,
    title: str,
    file_name: str,
    content_type: str,
    tags: list[str],
    checksum_sha256: str,
    size_bytes: int,
) -> Document:
    return Document(
        id=str(uuid4()),
        tenant_id=tenant_id,
        title=title,
        file_name=file_name,
        content_type=content_type,
        status=DocumentStatus.QUEUED.value,
        version="v1",
        tags=tags,
        source="rustfs",
        checksum_sha256=checksum_sha256,
        size_bytes=size_bytes,
    )


@router.get("/documents", response_model=DocumentListResponse)
async def list_documents(
    tenant_id: str = Query(...),
    db: Session = Depends(get_db_session),
) -> DocumentListResponse:
    statement = (
        select(Document)
        .where(Document.tenant_id == tenant_id)
        .order_by(Document.created_at.desc())
    )
    documents = list(db.scalars(statement).all())
    document_ids = [item.id for item in documents]
    jobs_by_document: dict[str, list[ProcessingJob]] = {}
    current_versions_by_document: dict[str, DocumentVersion] = {}

    if document_ids:
        all_jobs = list(
            db.scalars(
                select(ProcessingJob)
                .where(ProcessingJob.document_id.in_(document_ids))
                .order_by(ProcessingJob.created_at.desc())
            ).all()
        )
        for job in all_jobs:
            jobs_by_document.setdefault(job.document_id, []).append(job)

        current_versions = list(
            db.scalars(
                select(DocumentVersion).where(
                    DocumentVersion.document_id.in_(document_ids),
                    DocumentVersion.is_current.is_(True),
                )
            ).all()
        )
        current_versions_by_document = {
            version.document_id: version for version in current_versions
        }

    items = [
        build_document_item(
            item,
            jobs_by_document.get(item.id, []),
            current_versions_by_document.get(item.id),
        )
        for item in documents
    ]
    return DocumentListResponse(items=items, total=len(items))


@router.get("/documents/{document_id}", response_model=DocumentItem)
async def get_document(
    document_id: str,
    tenant_id: str = Query(...),
    db: Session = Depends(get_db_session),
) -> DocumentItem:
    document = get_document_for_tenant(db, document_id, tenant_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    jobs = list(
        db.scalars(
            select(ProcessingJob)
            .where(ProcessingJob.document_id == document.id)
            .order_by(ProcessingJob.created_at.desc())
        ).all()
    )
    return build_document_item(document, jobs, current_version_for_document(db, document.id))


@router.get("/documents/{document_id}/versions", response_model=DocumentVersionListResponse)
async def list_document_versions(
    document_id: str,
    tenant_id: str = Query(...),
    db: Session = Depends(get_db_session),
) -> DocumentVersionListResponse:
    document = get_document_for_tenant(db, document_id, tenant_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    versions = list(
        db.scalars(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document_id)
            .order_by(DocumentVersion.version_number.desc())
        ).all()
    )
    items = [build_version_item(item) for item in versions]
    return DocumentVersionListResponse(items=items, total=len(items))


@router.post(
    "/documents/upload",
    response_model=UploadAcceptedResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    tenant_id: str = Form(...),
    title: str = Form(...),
    tags: str = Form(default=""),
    file: UploadFile = File(...),
    db: Session = Depends(get_db_session),
) -> UploadAcceptedResponse:
    get_active_tenant(db, tenant_id)
    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    if len(payload) > settings.document_max_upload_bytes:
        raise HTTPException(status_code=413, detail="Uploaded file exceeds max configured size")

    checksum_sha256 = hashlib.sha256(payload).hexdigest()
    existing_document = db.scalars(
        select(Document).where(
            Document.tenant_id == tenant_id,
            Document.checksum_sha256 == checksum_sha256,
        )
    ).first()
    if existing_document:
        existing_job = latest_job_for_document(db, existing_document.id)
        existing_version = current_version_for_document(db, existing_document.id)
        if not existing_job or not existing_version:
            raise HTTPException(status_code=409, detail="Duplicate document exists without job")
        return UploadAcceptedResponse(
            document=build_document_item(
                existing_document,
                [existing_job],
                current_version_for_document(db, existing_document.id),
            ),
            root_job=build_processing_job_item(existing_job),
            object_key=existing_version.object_key,
            version=build_version_item(existing_version),
        )

    normalized_tags = [item.strip() for item in tags.split(",") if item.strip()]
    file_name = file.filename or "upload.bin"
    document = create_root_document(
        tenant_id=tenant_id,
        title=title,
        file_name=file_name,
        content_type=file.content_type or "application/octet-stream",
        tags=normalized_tags,
        checksum_sha256=checksum_sha256,
        size_bytes=len(payload),
    )
    db.add(document)
    db.flush()

    version = DocumentVersion(
        id=str(uuid4()),
        document_id=document.id,
        version_label="v1",
        version_number=1,
        object_key=str(PurePosixPath(tenant_id) / "documents" / document.id / "v1" / "raw" / file_name),
        bucket_name=settings.rustfs_bucket_raw,
        checksum_sha256=checksum_sha256,
        size_bytes=len(payload),
        status=DocumentStatus.QUEUED.value,
        processing_scope="full",
        is_current=True,
        effective_from=utcnow(),
    )
    stored_object = storage_client.upload_bytes(
        bucket_name=settings.rustfs_bucket_raw,
        object_key=version.object_key,
        payload=payload,
        content_type=file.content_type or "application/octet-stream",
        metadata={"tenant_id": tenant_id, "document_id": document.id, "version_label": "v1"},
    )
    version.object_key = stored_object.object_key
    version.bucket_name = stored_object.bucket_name
    artifact = DocumentArtifact(
        document_id=document.id,
        document_version_id=version.id,
        artifact_type="raw_upload",
        bucket_name=stored_object.bucket_name,
        object_key=stored_object.object_key,
        content_type=file.content_type or "application/octet-stream",
        artifact_metadata={"version_label": "v1", "checksum_sha256": checksum_sha256},
    )
    root_job = ProcessingJob(
        tenant_id=tenant_id,
        document_id=document.id,
        job_type="document.parse",
        queue_name="document.parse",
        status=JobStatus.QUEUED.value,
        payload={
            "bucket_name": stored_object.bucket_name,
            "object_key": stored_object.object_key,
            "file_name": file_name,
            "document_version_id": version.id,
            "version_label": "v1",
            "processing_mode": "full",
        },
    )

    db.add(version)
    db.add(artifact)
    db.add(root_job)
    db.commit()
    db.refresh(root_job)
    db.refresh(document)
    db.refresh(version)

    enqueue_root_job(db, root_job=root_job, document=document, tenant_id=tenant_id)
    return UploadAcceptedResponse(
        document=build_document_item(document, [root_job], version),
        root_job=build_processing_job_item(root_job),
        object_key=stored_object.object_key,
        version=build_version_item(version),
    )


@router.post(
    "/documents/{document_id}/versions/upload",
    response_model=UploadAcceptedResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document_version(
    document_id: str,
    tenant_id: str = Form(...),
    title: str | None = Form(default=None),
    tags: str = Form(default=""),
    effective_from: str | None = Form(default=None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db_session),
) -> UploadAcceptedResponse:
    get_active_tenant(db, tenant_id)
    document = get_document_for_tenant(db, document_id, tenant_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    if len(payload) > settings.document_max_upload_bytes:
        raise HTTPException(status_code=413, detail="Uploaded file exceeds max configured size")

    normalized_tags = [item.strip() for item in tags.split(",") if item.strip()] or document.tags
    version, root_job = persist_version_upload(
        db,
        document=document,
        tenant_id=document.tenant_id,
        title=title or document.title,
        tags=normalized_tags,
        upload_file=file,
        payload=payload,
        effective_from=parse_effective_from(effective_from),
    )
    enqueue_root_job(db, root_job=root_job, document=document, tenant_id=document.tenant_id)
    return UploadAcceptedResponse(
        document=build_document_item(document, [root_job], version),
        root_job=build_processing_job_item(root_job),
        object_key=version.object_key,
        version=build_version_item(version),
    )


@router.post("/documents/{document_id}/reprocess", response_model=ProcessingJobItem)
async def reprocess_document(
    document_id: str,
    payload: DocumentReprocessRequest,
    tenant_id: str = Query(...),
    db: Session = Depends(get_db_session),
) -> ProcessingJobItem:
    get_active_tenant(db, tenant_id)
    document = get_document_for_tenant(db, document_id, tenant_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    target_version = (
        db.get(DocumentVersion, payload.document_version_id)
        if payload.document_version_id
        else current_version_for_document(db, document_id)
    )
    if not target_version or target_version.document_id != document_id:
        raise HTTPException(status_code=404, detail="Document version not found")

    document.status = DocumentStatus.QUEUED.value
    target_version.status = DocumentStatus.QUEUED.value
    target_version.processing_scope = payload.mode
    db.add(document)
    db.add(target_version)

    root_job = ProcessingJob(
        tenant_id=document.tenant_id,
        document_id=document.id,
        job_type="document.parse",
        queue_name="document.parse",
        status=JobStatus.QUEUED.value,
        payload={
            "bucket_name": target_version.bucket_name,
            "object_key": target_version.object_key,
            "file_name": document.file_name,
            "document_version_id": target_version.id,
            "version_label": target_version.version_label,
            "processing_mode": payload.mode,
            "reprocess_reason": payload.reason,
        },
    )
    db.add(root_job)
    db.commit()
    db.refresh(root_job)
    db.refresh(document)
    enqueue_root_job(db, root_job=root_job, document=document, tenant_id=document.tenant_id)
    return build_processing_job_item(root_job)


@router.delete("/documents/{document_id}", response_model=DocumentDeleteResponse)
async def delete_document(
    document_id: str,
    tenant_id: str = Query(...),
    db: Session = Depends(get_db_session),
) -> DocumentDeleteResponse:
    document = get_document_for_tenant(db, document_id, tenant_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    versions = list(
        db.scalars(
            select(DocumentVersion).where(DocumentVersion.document_id == document.id)
        ).all()
    )
    artifacts = list(
        db.scalars(
            select(DocumentArtifact).where(DocumentArtifact.document_id == document.id)
        ).all()
    )
    chunks = list(
        db.scalars(select(DocumentChunk).where(DocumentChunk.document_id == document.id)).all()
    )
    jobs = list(
        db.scalars(
            select(ProcessingJob).where(ProcessingJob.document_id == document.id)
        ).all()
    )
    chunk_ids = [item.id for item in chunks]

    storage_targets = {
        (version.bucket_name, version.object_key)
        for version in versions
    }
    storage_targets.update(
        (artifact.bucket_name, artifact.object_key)
        for artifact in artifacts
    )

    try:
        for job in jobs:
            safe_revoke_task(job.celery_task_id)

        for bucket_name, object_key in storage_targets:
            safe_delete_object(bucket_name=bucket_name, object_key=object_key)

        clear_document_graph(
            client=neo4j_client,
            document_id=document.id,
            tenant_id=document.tenant_id,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Document cleanup failed: {exc}") from exc

    if chunk_ids:
        db.execute(delete(ChunkEmbedding).where(ChunkEmbedding.document_chunk_id.in_(chunk_ids)))
        db.execute(delete(ChunkExtraction).where(ChunkExtraction.document_chunk_id.in_(chunk_ids)))
        db.execute(delete(DocumentChunk).where(DocumentChunk.id.in_(chunk_ids)))

    db.execute(delete(DocumentArtifact).where(DocumentArtifact.document_id == document.id))
    db.execute(delete(DocumentVersion).where(DocumentVersion.document_id == document.id))
    db.execute(delete(ProcessingJob).where(ProcessingJob.document_id == document.id))
    db.execute(delete(Document).where(Document.id == document.id))
    db.commit()

    return DocumentDeleteResponse(
        document_id=document.id,
        tenant_id=document.tenant_id,
        title=document.title,
        deleted=True,
    )


@router.get("/documents/{document_id}/preview/raw")
async def preview_raw_document(
    document_id: str,
    tenant_id: str = Query(...),
    db: Session = Depends(get_db_session),
) -> Response:
    document = get_document_for_tenant(db, document_id, tenant_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    version = current_version_for_document(db, document.id)
    if version is None:
        raise HTTPException(status_code=404, detail="Document version not found")

    payload = storage_client.download_bytes(
        bucket_name=version.bucket_name,
        object_key=version.object_key,
    )
    return Response(
        content=payload,
        media_type=document.content_type or "application/octet-stream",
        headers={"Content-Disposition": f'inline; filename="{document.file_name}"'},
    )


@router.get("/documents/{document_id}/preview/parsed", response_model=DocumentParsedPreviewResponse)
async def preview_parsed_document(
    document_id: str,
    tenant_id: str = Query(...),
    db: Session = Depends(get_db_session),
) -> DocumentParsedPreviewResponse:
    document = get_document_for_tenant(db, document_id, tenant_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    version = current_version_for_document(db, document.id)
    if version is None:
        raise HTTPException(status_code=404, detail="Document version not found")

    artifact = artifact_for_version(
        db,
        document_version_id=version.id,
        artifact_type="parsed_canonical_json",
    )
    if artifact is None:
        raise HTTPException(status_code=404, detail="Parsed preview not available yet")

    payload = storage_client.download_bytes(
        bucket_name=artifact.bucket_name,
        object_key=artifact.object_key,
    )
    parsed = json.loads(payload.decode("utf-8"))
    return DocumentParsedPreviewResponse(
        document_id=document.id,
        document_version_id=version.id,
        version_label=version.version_label,
        title=document.title,
        language=parsed.get("language", "unknown"),
        ocr_required=bool(parsed.get("ocr_required", False)),
        ocr_applied=bool(parsed.get("ocr_applied", False)),
        parse_quality_score=float(parsed.get("parse_quality_score", 0.0) or 0.0),
        parse_warnings=list(parsed.get("parse_warnings", [])),
        plain_text=str(parsed.get("plain_text", "")),
    )


@router.get("/documents/{document_id}/preview/chunks", response_model=DocumentChunkPreviewResponse)
async def preview_document_chunks(
    document_id: str,
    tenant_id: str = Query(...),
    db: Session = Depends(get_db_session),
) -> DocumentChunkPreviewResponse:
    document = get_document_for_tenant(db, document_id, tenant_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    version = current_version_for_document(db, document.id)
    if version is None:
        raise HTTPException(status_code=404, detail="Document version not found")

    chunk_rows = list(
        db.scalars(
            select(DocumentChunk)
            .where(DocumentChunk.document_version_id == version.id)
            .order_by(DocumentChunk.chunk_index.asc())
        ).all()
    )
    if not chunk_rows:
        raise HTTPException(status_code=404, detail="Chunk preview not available yet")

    return DocumentChunkPreviewResponse(
        document_id=document.id,
        document_version_id=version.id,
        version_label=version.version_label,
        title=document.title,
        chunk_target_tokens=settings.chunk_target_tokens,
        chunk_overlap_tokens=settings.chunk_overlap_tokens,
        total_chunks=len(chunk_rows),
        items=[
            DocumentChunkPreviewItem(
                chunk_id=chunk.id,
                chunk_index=chunk.chunk_index,
                section_name=chunk.section_name,
                heading_path=chunk.heading_path,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                source_offset_start=chunk.source_offset_start,
                source_offset_end=chunk.source_offset_end,
                token_estimate=chunk.token_estimate,
                parse_quality_score=chunk.parse_quality_score,
                content=chunk.content,
                metadata=chunk.chunk_metadata,
            )
            for chunk in chunk_rows
        ],
    )
