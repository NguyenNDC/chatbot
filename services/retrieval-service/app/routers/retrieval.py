import math

from fastapi import APIRouter, Depends
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from enterprise_ai_core.db import get_db_session
from enterprise_ai_core.embedding import get_embedding_provider
from enterprise_ai_core.models import ChunkEmbedding, Document, DocumentChunk
from enterprise_ai_core.schemas import Citation, QueryRequest, RetrievalChunk

router = APIRouter(tags=["retrieval"])
embedding_provider = get_embedding_provider()


@router.post("/retrieve")
async def retrieve(payload: QueryRequest, db: Session = Depends(get_db_session)) -> dict:
    contexts = vector_search(payload, db)
    source = "pgvector" if contexts else "empty"
    if not contexts:
        contexts = lexical_fallback(payload, db)
        source = "lexical-fallback" if contexts else "empty"
    retrieval_plan = {
        "intent": "policy_lookup",
        "vector_top_k": payload.top_k,
        "graph_expansion": payload.include_graph,
        "re_ranker": "phase-2-disabled",
        "source": source,
    }
    return {"plan": retrieval_plan, "contexts": [item.model_dump(mode="json") for item in contexts]}


def vector_search(payload: QueryRequest, db: Session) -> list[RetrievalChunk]:
    query_vector = embedding_provider.embed([payload.question])[0]
    statement = (
        select(DocumentChunk, ChunkEmbedding, Document)
        .join(ChunkEmbedding, ChunkEmbedding.document_chunk_id == DocumentChunk.id)
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(DocumentChunk.tenant_id == payload.tenant_id)
        .order_by(ChunkEmbedding.embedding.cosine_distance(query_vector))
        .limit(payload.top_k)
    )
    rows = db.execute(statement).all()
    items: list[RetrievalChunk] = []
    for chunk, embedding, document in rows:
        score = cosine_similarity(query_vector, list(embedding.embedding))
        items.append(
            RetrievalChunk(
                chunk_id=chunk.id,
                score=score,
                content=chunk.content,
                source=Citation(
                    document_id=document.id,
                    title=document.title,
                    section=chunk.section_name,
                    page=chunk.page_start,
                    chunk_id=chunk.id,
                ),
            )
        )
    return items


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    numerator = sum(a * b for a, b in zip(left, right, strict=False))
    left_norm = math.sqrt(sum(value * value for value in left)) or 1.0
    right_norm = math.sqrt(sum(value * value for value in right)) or 1.0
    return max(0.0, numerator / (left_norm * right_norm))


def lexical_fallback(payload: QueryRequest, db: Session) -> list[RetrievalChunk]:
    query_terms = [term for term in payload.question.split() if len(term) > 2][:4]
    if not query_terms:
        return []
    statement = (
        select(DocumentChunk, Document)
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(
            DocumentChunk.tenant_id == payload.tenant_id,
            or_(*[DocumentChunk.content.ilike(f"%{term}%") for term in query_terms]),
        )
        .order_by(DocumentChunk.chunk_index.asc())
        .limit(payload.top_k)
    )
    rows = db.execute(statement).all()
    return [
        RetrievalChunk(
            chunk_id=chunk.id,
            score=0.5,
            content=chunk.content,
            source=Citation(
                document_id=document.id,
                title=document.title,
                section=chunk.section_name,
                page=chunk.page_start,
                chunk_id=chunk.id,
            ),
        )
        for chunk, document in rows
    ]
