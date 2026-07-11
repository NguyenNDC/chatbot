from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .schemas import DocumentStatus, JobStatus

PIPELINE_STAGES = (
    "document.parse",
    "document.chunk",
    "document.embed",
    "graph.extract",
    "graph.upsert",
)

STAGE_LABELS: dict[str, str] = {
    "document.parse": "Parse canonical",
    "document.chunk": "Chunk + provenance",
    "document.embed": "Embedding",
    "graph.extract": "Entity extraction",
    "graph.upsert": "Neo4j upsert",
    "document.dead_letter": "Dead letter",
}

STAGE_PROGRESS_BANDS: dict[str, tuple[int, int]] = {
    "document.parse": (2, 18),
    "document.chunk": (18, 40),
    "document.embed": (40, 60),
    "graph.extract": (60, 90),
    "graph.upsert": (90, 100),
}

ACTIVE_JOB_STATUSES = {JobStatus.QUEUED.value, JobStatus.RUNNING.value}


@dataclass(frozen=True)
class JobProgressSnapshot:
    stage: str | None
    stage_label: str | None
    stage_order: int
    status: str | None
    progress_percent: int
    progress_current: int | None
    progress_total: int | None
    progress_label: str
    progress_detail: str | None
    processing_mode: str | None
    version_label: str | None
    error_message: str | None


@dataclass(frozen=True)
class DocumentProgressSnapshot:
    selected_job: Any | None
    stage: str | None
    stage_label: str | None
    stage_order: int
    stage_status: str | None
    progress_percent: int
    progress_current: int | None
    progress_total: int | None
    progress_label: str
    progress_detail: str | None
    processing_mode: str | None
    error_message: str | None


def normalize_status(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "value"):
        return str(value.value)
    return str(value)


def stage_label(stage_name: str | None) -> str | None:
    if not stage_name:
        return None
    return STAGE_LABELS.get(stage_name, stage_name)


def stage_order(stage_name: str | None) -> int:
    if not stage_name:
        return 0
    try:
        return PIPELINE_STAGES.index(stage_name) + 1
    except ValueError:
        return 0


def job_payload(job: Any) -> dict[str, Any]:
    payload = getattr(job, "payload", {}) or {}
    if isinstance(payload, dict):
        return payload
    return {}


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _count_from_payload_list(value: Any) -> int | None:
    if isinstance(value, list):
        return len(value)
    return _as_int(value)


def _clamp_percent(value: float | int) -> int:
    return max(0, min(100, int(round(value))))


def _progress_from_ratio(
    *,
    stage_name: str | None,
    ratio: float | None,
    status: str | None,
) -> int:
    if status == JobStatus.COMPLETED.value:
        if stage_name == "graph.upsert":
            return 100
        band = STAGE_PROGRESS_BANDS.get(stage_name or "", (0, 100))
        return band[1]

    if status == JobStatus.FAILED.value:
        band = STAGE_PROGRESS_BANDS.get(stage_name or "", (0, 100))
        base, end = band
        return _clamp_percent(max(base + 4, base + ((end - base) * 0.5)))

    band = STAGE_PROGRESS_BANDS.get(stage_name or "", (0, 100))
    base, end = band
    if ratio is None:
        if status == JobStatus.RUNNING.value:
            return _clamp_percent(base + ((end - base) * 0.45))
        if status == JobStatus.QUEUED.value:
            return _clamp_percent(max(base, 1))
        return _clamp_percent(base)
    return _clamp_percent(base + ((end - base) * ratio))


def build_job_progress_snapshot(job: Any) -> JobProgressSnapshot:
    payload = job_payload(job)
    current_status = normalize_status(getattr(job, "status", None))
    current_stage = getattr(job, "job_type", None)
    current_label = stage_label(current_stage)
    current_order = stage_order(current_stage)
    current = None
    total = None
    detail = None

    if current_stage == "graph.extract":
        current = _as_int(payload.get("extraction_completed_unique_chunks"))
        total = _as_int(payload.get("extraction_total_unique_chunks"))
        resumed = _as_int(payload.get("extraction_resumed_unique_chunk_count"))
        if current is None or total is None:
            current = _as_int(payload.get("extraction_completed_chunks"))
            total = _as_int(payload.get("extraction_total_chunks"))
            resumed = _as_int(payload.get("extraction_resumed_chunk_count"))
        if current is not None and total:
            detail = f"{current}/{total} chunks extracted"
            if resumed:
                detail = f"{detail} | {resumed} resumed"
        elif current is not None:
            detail = f"{current} chunks extracted"
    elif current_stage == "document.embed":
        current = _as_int(payload.get("embedding_count"))
        total = _count_from_payload_list(payload.get("chunk_ids_requiring_embedding"))
        if total is None:
            total = _as_int(payload.get("chunk_count"))
        if current is not None and total:
            detail = f"{current}/{total} embeddings generated"
        elif current is not None:
            detail = f"{current} embeddings generated"
    elif current_stage == "document.chunk":
        current = _as_int(payload.get("chunk_count"))
        chunk_delta = payload.get("chunk_delta") if isinstance(payload.get("chunk_delta"), dict) else {}
        new_or_changed = _as_int(chunk_delta.get("new_or_changed")) or 0
        reused = _as_int(chunk_delta.get("reused")) or 0
        removed = _as_int(chunk_delta.get("removed")) or 0
        if current is not None:
            detail = f"{current} chunks | {new_or_changed} new/changed | {reused} reused | {removed} removed"
    elif current_stage == "document.parse":
        parse_quality = payload.get("parse_quality_score")
        if parse_quality is not None:
            try:
                detail = f"Parse quality {float(parse_quality):.2f}"
            except (TypeError, ValueError):
                detail = None
    elif current_stage == "graph.upsert":
        current = _as_int(payload.get("upserted_extraction_count"))
        total = _as_int(payload.get("upsert_total_extraction_count"))
        resumed = _as_int(payload.get("upsert_resumed_extraction_count")) or 0
        if current is not None and total:
            detail = f"{current}/{total} chunk extractions synced to Neo4j"
            if resumed > 0:
                detail = f"{detail} | {resumed} resumed"
        elif current is not None:
            detail = f"{current} chunk extractions synced to Neo4j"

    ratio = None
    if current is not None and total and total > 0:
        ratio = min(max(current / total, 0.0), 1.0)

    percent = _progress_from_ratio(stage_name=current_stage, ratio=ratio, status=current_status)

    if current_status == JobStatus.COMPLETED.value:
        label = "Pipeline completed" if current_stage == "graph.upsert" else f"{current_label} completed"
    elif current_status == JobStatus.FAILED.value:
        label = f"{current_label} failed"
    elif current_status == JobStatus.RUNNING.value:
        label = f"{current_label} running"
    elif current_status == JobStatus.QUEUED.value:
        label = f"Queued for {current_label.lower()}" if current_label else "Queued"
    else:
        label = current_label or "Unknown stage"

    return JobProgressSnapshot(
        stage=current_stage,
        stage_label=current_label,
        stage_order=current_order,
        status=current_status,
        progress_percent=percent,
        progress_current=current,
        progress_total=total,
        progress_label=label,
        progress_detail=detail,
        processing_mode=str(payload.get("processing_mode")) if payload.get("processing_mode") else None,
        version_label=str(payload.get("version_label")) if payload.get("version_label") else None,
        error_message=getattr(job, "error_message", None),
    )


def _job_matches_version(job: Any, current_version_id: str | None) -> bool:
    if current_version_id is None:
        return True
    payload_version_id = job_payload(job).get("document_version_id")
    if not payload_version_id:
        return True
    return str(payload_version_id) == current_version_id


def _job_sort_key(job: Any) -> tuple[int, int, datetime]:
    snapshot = build_job_progress_snapshot(job)
    status_priority = {
        JobStatus.RUNNING.value: 3,
        JobStatus.QUEUED.value: 2,
        JobStatus.FAILED.value: 1,
        JobStatus.COMPLETED.value: 0,
    }.get(snapshot.status or "", -1)
    created_at = getattr(job, "created_at", None) or datetime.min.replace(tzinfo=timezone.utc)
    return status_priority, snapshot.stage_order, created_at


def select_document_job(
    *,
    jobs: list[Any],
    current_version_id: str | None,
    document_status: Any,
) -> Any | None:
    if not jobs:
        return None

    version_jobs = [job for job in jobs if _job_matches_version(job, current_version_id)]
    candidates = version_jobs or jobs

    active_jobs = [
        job
        for job in candidates
        if normalize_status(getattr(job, "status", None)) in ACTIVE_JOB_STATUSES
    ]
    if active_jobs:
        return max(active_jobs, key=_job_sort_key)

    if normalize_status(document_status) == DocumentStatus.FAILED.value:
        failed_jobs = [
            job
            for job in candidates
            if normalize_status(getattr(job, "status", None)) == JobStatus.FAILED.value
        ]
        if failed_jobs:
            return max(failed_jobs, key=_job_sort_key)

    completed_jobs = [
        job
        for job in candidates
        if normalize_status(getattr(job, "status", None)) == JobStatus.COMPLETED.value
    ]
    if completed_jobs:
        return max(completed_jobs, key=_job_sort_key)

    return max(candidates, key=_job_sort_key)


def build_document_progress_snapshot(
    *,
    document_status: Any,
    jobs: list[Any],
    current_version_id: str | None,
) -> DocumentProgressSnapshot:
    normalized_document_status = normalize_status(document_status)
    selected_job = select_document_job(
        jobs=jobs,
        current_version_id=current_version_id,
        document_status=document_status,
    )

    if selected_job is None:
        if normalized_document_status == DocumentStatus.PROCESSED.value:
            return DocumentProgressSnapshot(
                selected_job=None,
                stage="graph.upsert",
                stage_label=stage_label("graph.upsert"),
                stage_order=len(PIPELINE_STAGES),
                stage_status=JobStatus.COMPLETED.value,
                progress_percent=100,
                progress_current=None,
                progress_total=None,
                progress_label="Pipeline completed",
                progress_detail="Document is ready for chatbot and retrieval.",
                processing_mode=None,
                error_message=None,
            )
        if normalized_document_status == DocumentStatus.FAILED.value:
            return DocumentProgressSnapshot(
                selected_job=None,
                stage=None,
                stage_label=None,
                stage_order=0,
                stage_status=JobStatus.FAILED.value,
                progress_percent=0,
                progress_current=None,
                progress_total=None,
                progress_label="Pipeline failed",
                progress_detail=None,
                processing_mode=None,
                error_message=None,
            )
        return DocumentProgressSnapshot(
            selected_job=None,
            stage="document.parse",
            stage_label=stage_label("document.parse"),
            stage_order=1,
            stage_status=JobStatus.QUEUED.value,
            progress_percent=1,
            progress_current=None,
            progress_total=None,
            progress_label="Queued for parse canonical",
            progress_detail=None,
            processing_mode=None,
            error_message=None,
        )

    job_snapshot = build_job_progress_snapshot(selected_job)
    progress_percent = job_snapshot.progress_percent
    progress_label = job_snapshot.progress_label
    progress_detail = job_snapshot.progress_detail
    stage_status = job_snapshot.status

    if normalized_document_status == DocumentStatus.PROCESSED.value:
        progress_percent = 100
        progress_label = "Pipeline completed"
        progress_detail = "Document is ready for chatbot and retrieval."
        stage_status = JobStatus.COMPLETED.value
    elif normalized_document_status == DocumentStatus.FAILED.value:
        progress_label = job_snapshot.progress_label if job_snapshot.stage_label else "Pipeline failed"
        if not progress_detail and job_snapshot.error_message:
            progress_detail = job_snapshot.error_message
        stage_status = JobStatus.FAILED.value
    elif (
        stage_status == JobStatus.COMPLETED.value
        and normalized_document_status in {DocumentStatus.QUEUED.value, DocumentStatus.PROCESSING.value}
    ):
        progress_label = f"{job_snapshot.stage_label} completed, waiting next stage"

    return DocumentProgressSnapshot(
        selected_job=selected_job,
        stage=job_snapshot.stage,
        stage_label=job_snapshot.stage_label,
        stage_order=job_snapshot.stage_order,
        stage_status=stage_status,
        progress_percent=progress_percent,
        progress_current=job_snapshot.progress_current,
        progress_total=job_snapshot.progress_total,
        progress_label=progress_label,
        progress_detail=progress_detail,
        processing_mode=job_snapshot.processing_mode,
        error_message=job_snapshot.error_message,
    )
