from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from enterprise_ai_core.db import get_db_session
from enterprise_ai_core.graph_upsert import clear_tenant_graph
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
from enterprise_ai_core.schemas import TenantCreateRequest, TenantItem, TenantListResponse
from enterprise_ai_core.storage import RustFSStorageClient

router = APIRouter(tags=["tenants"])
storage_client = RustFSStorageClient()
neo4j_client = get_neo4j_client()


def build_tenant_item(tenant: Tenant, document_count: int) -> TenantItem:
    return TenantItem(
        id=tenant.id,
        display_name=tenant.display_name,
        description=tenant.description,
        status=tenant.status,
        document_count=document_count,
        created_at=tenant.created_at,
    )


def safe_delete_object(*, bucket_name: str, object_key: str) -> None:
    try:
        storage_client.delete_object(bucket_name=bucket_name, object_key=object_key)
    except ClientError:
        # Missing or already-deleted objects should not block tenant cleanup.
        pass


@router.get("/tenants", response_model=TenantListResponse)
async def list_tenants(db: Session = Depends(get_db_session)) -> TenantListResponse:
    tenants = list(
        db.scalars(
            select(Tenant).where(Tenant.status == "active").order_by(Tenant.created_at.desc())
        ).all()
    )
    counts = {
        tenant_id: count
        for tenant_id, count in db.execute(
            select(Document.tenant_id, func.count(Document.id)).group_by(Document.tenant_id)
        ).all()
    }
    items = [build_tenant_item(item, counts.get(item.id, 0)) for item in tenants]
    return TenantListResponse(items=items, total=len(items))


@router.post("/tenants", response_model=TenantItem, status_code=status.HTTP_201_CREATED)
async def create_tenant(
    payload: TenantCreateRequest,
    db: Session = Depends(get_db_session),
) -> TenantItem:
    tenant = db.get(Tenant, payload.id)
    if tenant and tenant.status == "active":
        raise HTTPException(status_code=409, detail="Tenant already exists")

    if tenant is None:
        tenant = Tenant(
            id=payload.id,
            display_name=payload.display_name,
            description=payload.description,
            status="active",
        )
    else:
        tenant.display_name = payload.display_name
        tenant.description = payload.description
        tenant.status = "active"

    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    return build_tenant_item(tenant, 0)


@router.delete("/tenants/{tenant_id}", response_model=TenantItem)
async def delete_tenant(tenant_id: str, db: Session = Depends(get_db_session)) -> TenantItem:
    tenant = db.get(Tenant, tenant_id)
    if tenant is None or tenant.status != "active":
        raise HTTPException(status_code=404, detail="Tenant not found")

    documents = list(
        db.scalars(select(Document).where(Document.tenant_id == tenant_id)).all()
    )
    document_ids = [item.id for item in documents]

    versions = list(
        db.scalars(
            select(DocumentVersion).where(DocumentVersion.document_id.in_(document_ids))
        ).all()
    ) if document_ids else []
    version_ids = [item.id for item in versions]

    artifacts = list(
        db.scalars(
            select(DocumentArtifact).where(DocumentArtifact.document_id.in_(document_ids))
        ).all()
    ) if document_ids else []

    chunks = list(
        db.scalars(select(DocumentChunk).where(DocumentChunk.tenant_id == tenant_id)).all()
    )
    chunk_ids = [item.id for item in chunks]

    try:
        for version in versions:
            safe_delete_object(bucket_name=version.bucket_name, object_key=version.object_key)
        for artifact in artifacts:
            safe_delete_object(bucket_name=artifact.bucket_name, object_key=artifact.object_key)

        clear_tenant_graph(client=neo4j_client, tenant_id=tenant_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Tenant cleanup failed: {exc}") from exc

    if chunk_ids:
        db.execute(delete(ChunkEmbedding).where(ChunkEmbedding.document_chunk_id.in_(chunk_ids)))
        db.execute(delete(ChunkExtraction).where(ChunkExtraction.document_chunk_id.in_(chunk_ids)))
        db.execute(delete(DocumentChunk).where(DocumentChunk.id.in_(chunk_ids)))

    if document_ids:
        db.execute(delete(DocumentArtifact).where(DocumentArtifact.document_id.in_(document_ids)))
        db.execute(delete(DocumentVersion).where(DocumentVersion.document_id.in_(document_ids)))
        db.execute(delete(ProcessingJob).where(ProcessingJob.document_id.in_(document_ids)))
        db.execute(delete(Document).where(Document.id.in_(document_ids)))

    deleted_snapshot = build_tenant_item(tenant, len(documents))
    db.delete(tenant)
    db.commit()
    return deleted_snapshot.model_copy(update={"status": "deleted"})
