import hashlib
from pathlib import PurePosixPath
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from enterprise_ai_core.config import get_settings
from enterprise_ai_core.db import get_db_session
from enterprise_ai_core.models import Document, DocumentArtifact, DocumentVersion, ProcessingJob
from enterprise_ai_core.queue import get_celery_app
from enterprise_ai_core.schemas import (
    DocumentItem,
    DocumentListResponse,
    DocumentStatus,
    JobStatus,
    ProcessingJobItem,
    UploadAcceptedResponse,
)
from enterprise_ai_core.storage import RustFSStorageClient

router = APIRouter(tags=["documents"])
settings = get_settings()
storage_client = RustFSStorageClient()
celery_app = get_celery_app()


def build_document_item(document: Document, latest_job: ProcessingJob | None) -> DocumentItem:
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
        current_job_type=latest_job.job_type if latest_job else None,
        current_job_status=JobStatus(latest_job.status) if latest_job else None,
        created_at=document.created_at,
    )


def latest_job_for_document(db: Session, document_id: str) -> ProcessingJob | None:
    statement = (
        select(ProcessingJob)
        .where(ProcessingJob.document_id == document_id)
        .order_by(ProcessingJob.created_at.desc())
    )
    return db.scalars(statement).first()


@router.get("/documents", response_model=DocumentListResponse)
async def list_documents(db: Session = Depends(get_db_session)) -> DocumentListResponse:
    statement = select(Document).order_by(Document.created_at.desc())
    documents = list(db.scalars(statement).all())
    items = [build_document_item(item, latest_job_for_document(db, item.id)) for item in documents]
    return DocumentListResponse(items=items, total=len(items))


@router.get("/documents/{document_id}", response_model=DocumentItem)
async def get_document(document_id: str, db: Session = Depends(get_db_session)) -> DocumentItem:
    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    return build_document_item(document, latest_job_for_document(db, document.id))


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
    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    checksum_sha256 = hashlib.sha256(payload).hexdigest()
    existing_document = db.scalars(
        select(Document).where(
            Document.tenant_id == tenant_id, Document.checksum_sha256 == checksum_sha256
        )
    ).first()
    if existing_document:
        existing_job = latest_job_for_document(db, existing_document.id)
        if not existing_job:
            raise HTTPException(status_code=409, detail="Duplicate document exists without job")
        return UploadAcceptedResponse(
            document=build_document_item(existing_document, existing_job),
            root_job=ProcessingJobItem.model_validate(existing_job),
            object_key=db.scalars(
                select(DocumentVersion.object_key).where(
                    DocumentVersion.document_id == existing_document.id
                )
            ).first(),
        )

    normalized_tags = [item.strip() for item in tags.split(",") if item.strip()]
    document_id = str(uuid4())
    version_label = "v1"
    file_name = file.filename or "upload.bin"
    object_key = str(
        PurePosixPath(tenant_id) / "documents" / document_id / version_label / "raw" / file_name
    )

    stored_object = storage_client.upload_bytes(
        bucket_name=settings.rustfs_bucket_raw,
        object_key=object_key,
        payload=payload,
        content_type=file.content_type or "application/octet-stream",
        metadata={"tenant_id": tenant_id, "document_id": document_id},
    )

    document_version_id = str(uuid4())

    document = Document(
        id=document_id,
        tenant_id=tenant_id,
        title=title,
        file_name=file_name,
        content_type=file.content_type or "application/octet-stream",
        status=DocumentStatus.QUEUED.value,
        version=version_label,
        tags=normalized_tags,
        source="rustfs",
        checksum_sha256=checksum_sha256,
        size_bytes=len(payload),
    )
    document_version = DocumentVersion(
        id=document_version_id,
        document_id=document_id,
        version_label=version_label,
        object_key=stored_object.object_key,
        bucket_name=stored_object.bucket_name,
        checksum_sha256=checksum_sha256,
        size_bytes=len(payload),
    )
    artifact = DocumentArtifact(
        document_id=document_id,
        document_version_id=document_version_id,
        artifact_type="raw_upload",
        bucket_name=stored_object.bucket_name,
        object_key=stored_object.object_key,
        content_type=file.content_type or "application/octet-stream",
    )
    root_job = ProcessingJob(
        tenant_id=tenant_id,
        document_id=document_id,
        job_type="document.parse",
        queue_name="document.parse",
        status=JobStatus.QUEUED.value,
        payload={
            "bucket_name": stored_object.bucket_name,
            "object_key": stored_object.object_key,
            "file_name": file_name,
        },
    )

    db.add(document)
    db.add(document_version)
    db.add(artifact)
    db.add(root_job)
    db.commit()
    db.refresh(root_job)
    db.refresh(document)

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
        raise HTTPException(status_code=502, detail="Upload persisted but queue publish failed")

    return UploadAcceptedResponse(
        document=build_document_item(document, root_job),
        root_job=ProcessingJobItem.model_validate(root_job),
        object_key=stored_object.object_key,
    )
