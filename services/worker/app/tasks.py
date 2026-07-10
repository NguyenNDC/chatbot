from datetime import datetime, timezone

from enterprise_ai_core.db import SessionLocal
from enterprise_ai_core.models import Document, ProcessingJob
from enterprise_ai_core.queue import get_celery_app
from enterprise_ai_core.schemas import DocumentStatus, JobStatus

celery_app = get_celery_app()

NEXT_STAGE: dict[str, str | None] = {
    "document.parse": "document.chunk",
    "document.chunk": "document.embed",
    "document.embed": "graph.extract",
    "graph.extract": "graph.upsert",
    "graph.upsert": None,
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


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


def advance_job(stage_name: str, job_id: str, document_id: str) -> None:
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

        job.status = JobStatus.COMPLETED.value
        job.completed_at = utcnow()
        session.add(job)

        next_stage = NEXT_STAGE[stage_name]
        if next_stage is None:
            document.status = DocumentStatus.PROCESSED.value
            session.add(document)
            session.commit()
            return

        session.commit()
    except Exception as exc:
        session.rollback()
        if "job" in locals() and job is not None:
            job.status = JobStatus.FAILED.value
            job.error_message = str(exc)
            job.completed_at = utcnow()
            session.add(job)
        if "document" in locals() and document is not None:
            document.status = DocumentStatus.FAILED.value
            session.add(document)
        session.commit()
        raise
    finally:
        session.close()

    enqueue_next_stage(current_job=job, document=document, next_stage=next_stage)


@celery_app.task(name="document.parse", bind=True)
def document_parse(self, job_id: str, document_id: str, tenant_id: str) -> dict:
    advance_job("document.parse", job_id, document_id)
    return {"job_id": job_id, "document_id": document_id, "tenant_id": tenant_id}


@celery_app.task(name="document.chunk", bind=True)
def document_chunk(self, job_id: str, document_id: str, tenant_id: str) -> dict:
    advance_job("document.chunk", job_id, document_id)
    return {"job_id": job_id, "document_id": document_id, "tenant_id": tenant_id}


@celery_app.task(name="document.embed", bind=True)
def document_embed(self, job_id: str, document_id: str, tenant_id: str) -> dict:
    advance_job("document.embed", job_id, document_id)
    return {"job_id": job_id, "document_id": document_id, "tenant_id": tenant_id}


@celery_app.task(name="graph.extract", bind=True)
def graph_extract(self, job_id: str, document_id: str, tenant_id: str) -> dict:
    advance_job("graph.extract", job_id, document_id)
    return {"job_id": job_id, "document_id": document_id, "tenant_id": tenant_id}


@celery_app.task(name="graph.upsert", bind=True)
def graph_upsert(self, job_id: str, document_id: str, tenant_id: str) -> dict:
    advance_job("graph.upsert", job_id, document_id)
    return {"job_id": job_id, "document_id": document_id, "tenant_id": tenant_id}
