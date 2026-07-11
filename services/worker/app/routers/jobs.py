from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from enterprise_ai_core.db import get_db_session
from enterprise_ai_core.models import ProcessingJob
from enterprise_ai_core.progress import build_job_progress_snapshot
from enterprise_ai_core.schemas import ProcessingJobItem, ProcessingJobListResponse

router = APIRouter(tags=["jobs"])


def build_processing_job_item(job: ProcessingJob) -> ProcessingJobItem:
    snapshot = build_job_progress_snapshot(job)
    return ProcessingJobItem(
        id=job.id,
        tenant_id=job.tenant_id,
        document_id=job.document_id,
        job_type=job.job_type,
        queue_name=job.queue_name,
        status=job.status,
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


@router.get("/jobs", response_model=ProcessingJobListResponse)
async def list_jobs(
    tenant_id: str = Query(...),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db_session),
) -> ProcessingJobListResponse:
    statement = (
        select(ProcessingJob)
        .where(ProcessingJob.tenant_id == tenant_id)
        .order_by(ProcessingJob.created_at.desc())
        .limit(limit)
    )
    jobs = list(db.scalars(statement).all())
    items = [build_processing_job_item(job) for job in jobs]
    return ProcessingJobListResponse(items=items, total=len(items))


@router.get("/jobs/{job_id}", response_model=ProcessingJobItem)
async def get_job(
    job_id: str,
    tenant_id: str = Query(...),
    db: Session = Depends(get_db_session),
) -> ProcessingJobItem:
    statement = select(ProcessingJob).where(
        ProcessingJob.id == job_id,
        ProcessingJob.tenant_id == tenant_id,
    )
    job = db.scalars(statement).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return build_processing_job_item(job)

