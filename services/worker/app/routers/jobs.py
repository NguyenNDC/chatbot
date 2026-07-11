from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from enterprise_ai_core.db import get_db_session
from enterprise_ai_core.models import ProcessingJob
from enterprise_ai_core.schemas import ProcessingJobItem, ProcessingJobListResponse

router = APIRouter(tags=["jobs"])


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
    items = [ProcessingJobItem.model_validate(job) for job in jobs]
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
    return ProcessingJobItem.model_validate(job)

