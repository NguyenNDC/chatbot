import math
import re
from collections import defaultdict

from fastapi import APIRouter, Depends
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from enterprise_ai_core.config import get_settings
from enterprise_ai_core.db import get_db_session
from enterprise_ai_core.embedding import get_embedding_provider
from enterprise_ai_core.graphdb import get_neo4j_client
from enterprise_ai_core.models import ChunkEmbedding, Document, DocumentChunk
from enterprise_ai_core.schemas import Citation, QueryRequest, RetrievalChunk

router = APIRouter(tags=["retrieval"])
settings = get_settings()
embedding_provider = get_embedding_provider()
neo4j_client = get_neo4j_client()

STOP_TERMS = {
    "and",
    "are",
    "cho",
    "cua",
    "from",
    "khi",
    "la",
    "lam",
    "mot",
    "nhung",
    "nguoi",
    "noi",
    "sao",
    "sao",
    "sop",
    "tai",
    "the",
    "thu",
    "tren",
    "va",
    "voi",
}


@router.post("/retrieve")
async def retrieve(payload: QueryRequest, db: Session = Depends(get_db_session)) -> dict:
    query_terms = normalize_terms(payload.question)
    intent = classify_intent(payload.question)

    vector_contexts = vector_search(payload, db)
    try:
        graph_contexts = graph_search(payload, query_terms, db) if payload.include_graph else []
    except Exception:
        graph_contexts = []
    contexts = merge_contexts(vector_contexts, graph_contexts, payload.top_k)

    source = "hybrid" if vector_contexts and graph_contexts else "pgvector" if vector_contexts else "graph" if graph_contexts else "empty"
    if not contexts:
        contexts = lexical_fallback(payload, db, query_terms)
        source = "lexical-fallback" if contexts else "empty"

    retrieval_plan = {
        "intent": intent,
        "vector_top_k": payload.top_k,
        "graph_expansion": payload.include_graph,
        "graph_hops": min(3, max(1, settings.retrieval_graph_hops)),
        "graph_candidates": len(graph_contexts),
        "re_ranker": "weighted-hybrid-merge",
        "source": source,
    }
    return {"plan": retrieval_plan, "contexts": [item.model_dump(mode="json") for item in contexts]}


def classify_intent(question: str) -> str:
    lowered = question.lower()
    if any(term in lowered for term in {"lien quan", "quan he", "phu thuoc", "anh huong"}):
        return "relationship_lookup"
    if any(term in lowered for term in {"quy trinh", "quy dinh", "policy", "sop", "nghia vu"}):
        return "policy_lookup"
    return "semantic_lookup"


def normalize_terms(text: str) -> list[str]:
    tokens = [token for token in re.split(r"\W+", text.lower()) if len(token) >= 3]
    deduped: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        if token in STOP_TERMS or token in seen:
            continue
        seen.add(token)
        deduped.append(token)
    return deduped[:8]


def build_citation(document: Document, chunk: DocumentChunk) -> Citation:
    return Citation(
        document_id=document.id,
        document_version_id=chunk.document_version_id,
        title=document.title,
        section=chunk.section_name,
        page=chunk.page_start,
        chunk_id=chunk.id,
    )


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
                source=build_citation(document, chunk),
                retrieval_source="vector",
                vector_score=score,
                final_score=score,
            )
        )
    return items


def graph_search(
    payload: QueryRequest,
    query_terms: list[str],
    db: Session,
) -> list[RetrievalChunk]:
    if not query_terms:
        return []

    hops = min(3, max(1, settings.retrieval_graph_hops))
    cypher = f"""
    MATCH (seed:Entity)
    WHERE seed.tenant_id = $tenant_id
      AND any(
        term IN $terms WHERE toLower(seed.name) CONTAINS term
        OR any(alias IN coalesce(seed.aliases, []) WHERE toLower(alias) CONTAINS term)
      )
    WITH collect(DISTINCT seed) AS seeds
    UNWIND seeds AS seed
    OPTIONAL MATCH (seed)-[:RELATED_TO*1..{hops}]-(neighbor:Entity {{tenant_id: $tenant_id}})
    WITH [item IN collect(DISTINCT seed) + collect(DISTINCT neighbor) WHERE item IS NOT NULL] AS entities
    UNWIND entities AS entity
    WITH DISTINCT entity
    MATCH (entity)-[m:MENTIONED_IN]->(d:Document)
    RETURN d.id AS document_id,
           collect(DISTINCT entity.name) AS supporting_entities,
           max(coalesce(m.confidence, 0.5)) AS mention_confidence
    LIMIT $limit
    """
    with neo4j_client.driver.session() as session:
        rows = list(
            session.run(
                cypher,
                tenant_id=payload.tenant_id,
                terms=query_terms,
                limit=settings.retrieval_graph_candidate_limit,
            )
        )

    if not rows:
        return []

    doc_support: dict[str, dict] = {
        row["document_id"]: {
            "supporting_entities": [item for item in row["supporting_entities"] if item],
            "mention_confidence": float(row["mention_confidence"] or 0.0),
        }
        for row in rows
        if row["document_id"]
    }
    if not doc_support:
        return []

    statement = (
        select(DocumentChunk, Document)
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(
            DocumentChunk.tenant_id == payload.tenant_id,
            DocumentChunk.document_id.in_(list(doc_support.keys())),
        )
        .order_by(DocumentChunk.document_id.asc(), DocumentChunk.chunk_index.asc())
    )
    chunk_rows = db.execute(statement).all()

    ranked_by_document: dict[str, list[tuple[float, RetrievalChunk]]] = defaultdict(list)
    for chunk, document in chunk_rows:
        support = doc_support.get(document.id)
        if support is None:
            continue
        lexical_overlap = score_term_overlap(query_terms, chunk.content)
        entity_overlap = score_entity_overlap(support["supporting_entities"], chunk.content)
        graph_score = min(
            1.0,
            support["mention_confidence"] * 0.45 + lexical_overlap * 0.35 + entity_overlap * 0.20,
        )
        if graph_score <= 0:
            continue
        context = RetrievalChunk(
            chunk_id=chunk.id,
            score=graph_score,
            content=chunk.content,
            source=build_citation(document, chunk),
            retrieval_source="graph",
            graph_score=graph_score,
            final_score=graph_score,
            supporting_entities=support["supporting_entities"][:6],
        )
        ranked_by_document[document.id].append((graph_score, context))

    results: list[RetrievalChunk] = []
    for ranked_chunks in ranked_by_document.values():
        ranked_chunks.sort(key=lambda item: item[0], reverse=True)
        results.extend(context for _, context in ranked_chunks[:2])

    results.sort(key=lambda item: item.final_score or item.score, reverse=True)
    return results[: max(payload.top_k, settings.retrieval_graph_candidate_limit)]


def merge_contexts(
    vector_contexts: list[RetrievalChunk],
    graph_contexts: list[RetrievalChunk],
    top_k: int,
) -> list[RetrievalChunk]:
    merged: dict[str, RetrievalChunk] = {}
    for context in vector_contexts:
        merged[context.chunk_id] = context

    for context in graph_contexts:
        existing = merged.get(context.chunk_id)
        if existing is None:
            merged[context.chunk_id] = context.model_copy(
                update={
                    "score": context.graph_score or context.score,
                    "final_score": context.graph_score or context.score,
                }
            )
            continue

        vector_score = existing.vector_score if existing.vector_score is not None else existing.score
        graph_score = context.graph_score if context.graph_score is not None else context.score
        final_score = min(1.0, vector_score * 0.65 + graph_score * 0.35)
        merged[context.chunk_id] = existing.model_copy(
            update={
                "score": final_score,
                "retrieval_source": "hybrid",
                "graph_score": graph_score,
                "final_score": final_score,
                "supporting_entities": merge_entities(
                    existing.supporting_entities, context.supporting_entities
                ),
            }
        )

    items = list(merged.values())
    items.sort(key=lambda item: item.final_score or item.score, reverse=True)
    return items[:top_k]


def merge_entities(left: list[str], right: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for item in left + right:
        normalized = item.strip()
        if not normalized or normalized.lower() in seen:
            continue
        seen.add(normalized.lower())
        merged.append(normalized)
    return merged[:8]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    numerator = sum(a * b for a, b in zip(left, right, strict=False))
    left_norm = math.sqrt(sum(value * value for value in left)) or 1.0
    right_norm = math.sqrt(sum(value * value for value in right)) or 1.0
    return max(0.0, numerator / (left_norm * right_norm))


def lexical_fallback(
    payload: QueryRequest,
    db: Session,
    query_terms: list[str] | None = None,
) -> list[RetrievalChunk]:
    terms = query_terms or normalize_terms(payload.question)
    if not terms:
        return []
    statement = (
        select(DocumentChunk, Document)
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(
            DocumentChunk.tenant_id == payload.tenant_id,
            or_(*[DocumentChunk.content.ilike(f"%{term}%") for term in terms[:4]]),
        )
        .order_by(DocumentChunk.chunk_index.asc())
        .limit(payload.top_k)
    )
    rows = db.execute(statement).all()
    return [
        RetrievalChunk(
            chunk_id=chunk.id,
            score=score_term_overlap(terms, chunk.content) or 0.5,
            content=chunk.content,
            source=build_citation(document, chunk),
            retrieval_source="lexical",
            final_score=score_term_overlap(terms, chunk.content) or 0.5,
        )
        for chunk, document in rows
    ]


def score_term_overlap(query_terms: list[str], content: str) -> float:
    if not query_terms:
        return 0.0
    lowered = content.lower()
    hits = sum(1 for term in query_terms if term in lowered)
    return hits / len(query_terms)


def score_entity_overlap(entity_names: list[str], content: str) -> float:
    if not entity_names:
        return 0.0
    lowered = content.lower()
    hits = sum(1 for entity in entity_names if entity.lower() in lowered)
    return min(1.0, hits / len(entity_names))
