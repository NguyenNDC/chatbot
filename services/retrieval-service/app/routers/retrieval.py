import math
import re
import unicodedata
from collections import defaultdict

from fastapi import APIRouter, Depends
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from enterprise_ai_core.config import get_settings
from enterprise_ai_core.db import get_db_session
from enterprise_ai_core.embedding import get_embedding_provider
from enterprise_ai_core.graphdb import get_neo4j_client
from enterprise_ai_core.models import ChunkEmbedding, Document, DocumentChunk, DocumentVersion
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
    "sop",
    "tai",
    "the",
    "thu",
    "tren",
    "va",
    "voi",
}
VECTOR_CANDIDATE_MULTIPLIER = 4
VECTOR_CANDIDATE_FLOOR = 18
LEXICAL_SUPPLEMENT_TOP_K = 8
SHORT_CONTEXT_CHAR_THRESHOLD = 80
MEDIUM_CONTEXT_CHAR_THRESHOLD = 180


@router.post("/retrieve")
async def retrieve(payload: QueryRequest, db: Session = Depends(get_db_session)) -> dict:
    intent = classify_intent(payload)
    subqueries = build_subqueries(payload.question, intent)
    query_terms = normalize_terms(" ".join(subqueries))
    vector_contexts = vector_search(payload, db, subqueries, intent)
    lexical_contexts = lexical_fallback(
        payload,
        db,
        query_terms,
        intent,
        limit=max(payload.top_k, LEXICAL_SUPPLEMENT_TOP_K),
    )
    try:
        graph_contexts = (
            graph_search(payload, query_terms, db, intent)
            if payload.include_graph and graph_search_available(payload.tenant_id, db)
            else []
        )
    except Exception:
        graph_contexts = []

    contexts = merge_contexts(vector_contexts, graph_contexts, lexical_contexts)
    contexts = rerank_contexts(contexts, query_terms, intent)
    contexts = enforce_evidence_threshold(contexts)
    contexts = contexts[: payload.top_k]

    source = (
        "hybrid"
        if sum(bool(source_group) for source_group in (vector_contexts, graph_contexts, lexical_contexts)) >= 2
        else "pgvector"
        if vector_contexts
        else "lexical"
        if lexical_contexts
        else "graph"
        if graph_contexts
        else "empty"
    )
    if not contexts:
        contexts = lexical_fallback(payload, db, query_terms, intent)
        source = "lexical-fallback" if contexts else "empty"

    retrieval_plan = {
        "intent": intent,
        "query_mode": payload.query_mode,
        "subqueries": subqueries,
        "vector_top_k": payload.top_k,
        "graph_expansion": payload.include_graph,
        "graph_hops": min(3, max(1, settings.retrieval_graph_hops)),
        "graph_candidates": len(graph_contexts),
        "re_ranker": "heuristic-hybrid-rerank",
        "source": source,
        "insufficient_evidence": not contexts,
    }
    return {"plan": retrieval_plan, "contexts": [item.model_dump(mode="json") for item in contexts]}


def classify_intent(payload: QueryRequest) -> str:
    if payload.query_mode != "auto":
        return payload.query_mode
    lowered = payload.question.lower()
    if any(term in lowered for term in {"so sanh", "compare", "khac nhau", "giong nhau"}):
        return "compare"
    if any(
        term in lowered for term in {"hieu luc", "het hieu luc", "ngay", "thoi diem", "bao gio"}
    ):
        return "temporal"
    if any(term in lowered for term in {"tom tat", "summary", "tong quan"}):
        return "summary"
    return "lookup"


def build_subqueries(question: str, intent: str) -> list[str]:
    normalized = " ".join(question.split())
    if intent == "compare":
        lowered = normalized.lower()
        if " so sanh " in f" {lowered} ":
            parts = re.split(r"\bso sanh\b", normalized, flags=re.IGNORECASE)
            if len(parts) > 1:
                right = parts[-1].strip()
                pair = re.split(r"\bva\b|\bwith\b", right, flags=re.IGNORECASE)
                subqueries = [item.strip(" ?") for item in pair if item.strip(" ?")]
                if len(subqueries) >= 2:
                    return subqueries[:2]
    return [normalized]


def normalize_terms(text: str) -> list[str]:
    tokens = [token for token in re.split(r"\W+", normalize_search_text(text)) if len(token) >= 3]
    deduped: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        if token in STOP_TERMS or token in seen:
            continue
        seen.add(token)
        deduped.append(token)
    return deduped[:10]


def normalize_search_text(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text.lower()).replace("đ", "d")
    without_marks = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    return " ".join(re.sub(r"[^a-z0-9\s]", " ", without_marks).split())


def build_version_filters(payload: QueryRequest) -> list:
    filters = []
    if payload.version_ids:
        filters.append(DocumentVersion.id.in_(payload.version_ids))
    else:
        filters.append(DocumentVersion.is_current.is_(True))
    if payload.document_ids:
        filters.append(Document.id.in_(payload.document_ids))
    if payload.effective_at is not None:
        filters.append(DocumentVersion.effective_from <= payload.effective_at)
        filters.append(
            or_(
                DocumentVersion.effective_to.is_(None),
                DocumentVersion.effective_to >= payload.effective_at,
            )
        )
    return filters


def build_citation(
    db: Session,
    document: Document,
    version: DocumentVersion,
    chunk: DocumentChunk,
) -> Citation:
    provenance = find_section_provenance(db, chunk)
    document_label = infer_document_label(db, document, version)
    chapter = infer_chapter_label(chunk) or provenance["chapter"]
    article = infer_article_label(chunk) or provenance["article"]
    source_page = chunk.page_start or provenance["page"]
    section = infer_section_label(chunk, chapter, article)
    source_label = build_source_label(document_label, chapter, article, section, source_page)
    return Citation(
        document_id=document.id,
        document_version_id=version.id,
        title=document.title,
        file_name=document.file_name,
        section=section,
        section_path=chunk.heading_path,
        page=source_page,
        chunk_id=chunk.id,
        block_id=chunk.chunk_metadata.get("source_block_id"),
        document_label=document_label,
        chapter=chapter,
        article=article,
        source_label=source_label,
    )


def find_section_provenance(db: Session, chunk: DocumentChunk) -> dict[str, str | int | None]:
    rows = list(
        db.scalars(
            select(DocumentChunk)
            .where(
                DocumentChunk.document_id == chunk.document_id,
                DocumentChunk.document_version_id == chunk.document_version_id,
                DocumentChunk.chunk_index <= chunk.chunk_index,
            )
            .order_by(DocumentChunk.chunk_index.desc())
            .limit(80)
        ).all()
    )
    chapter: str | None = None
    article: str | None = None
    page: int | None = None
    for candidate in rows:
        if article is None:
            article = infer_article_label(candidate)
            if article:
                page = candidate.page_start
        if chapter is None:
            chapter = infer_chapter_label(candidate)
        if article and chapter:
            break
    return {"chapter": chapter, "article": article, "page": page}


def infer_document_label(db: Session, document: Document, version: DocumentVersion) -> str:
    rows = list(
        db.scalars(
            select(DocumentChunk)
            .where(
                DocumentChunk.document_id == document.id,
                DocumentChunk.document_version_id == version.id,
            )
            .order_by(DocumentChunk.chunk_index.asc())
            .limit(30)
        ).all()
    )
    header_text = "\n".join(chunk.content[:500] for chunk in rows)
    patterns = [
        r"^\s*(NGHỊ\s+ĐỊNH|NGHI\s+DINH)\s+(?:SỐ\s*)?([0-9/]+/[A-Z0-9Đ-]+)[^\n]{0,120}",
        r"^\s*(LUẬT|LUAT)\s+(?:SỐ\s*)?([0-9/]+/[A-Z0-9Đ-]+)[^\n]{0,120}",
        r"^\s*(THÔNG\s+TƯ|THONG\s+TU)\s+(?:SỐ\s*)?([0-9/]+/[A-Z0-9Đ-]+)[^\n]{0,120}",
        r"^\s*(QUYẾT\s+ĐỊNH|QUYET\s+DINH)\s+(?:SỐ\s*)?([0-9/]+/[A-Z0-9Đ-]+)[^\n]{0,120}",
    ]
    for pattern in patterns:
        match = re.search(pattern, header_text, flags=re.IGNORECASE | re.MULTILINE)
        if match:
            label = " ".join(match.group(0).split()).strip(" -–—.")
            if 4 <= len(label) <= 180:
                return normalize_legal_label(label)
    return document.title


def normalize_legal_label(label: str) -> str:
    replacements = {
        "NGHI DINH": "NGHỊ ĐỊNH",
        "LUAT": "LUẬT",
        "THONG TU": "THÔNG TƯ",
        "QUYET DINH": "QUYẾT ĐỊNH",
    }
    normalized = label
    for raw, corrected in replacements.items():
        normalized = re.sub(raw, corrected, normalized, flags=re.IGNORECASE)
    return normalized


def infer_chapter_label(chunk: DocumentChunk) -> str | None:
    heading_candidates = [
        *[str(item) for item in chunk.heading_path or []],
        chunk.section_name or "",
    ]
    for candidate in heading_candidates:
        match = re.search(
            r"\b(Chương|Chuong)\s+([IVXLCDM]+|\d+)\.?\s*([^\n.;:]{0,140})",
            candidate,
            flags=re.IGNORECASE,
        )
        if match:
            return format_chapter_match(match)

    match = re.search(
        r"(?:^|\n)\s*(Chương|Chuong)\s+([IVXLCDM]+|\d+)\.?\s*([^\n.;:]{0,140})",
        chunk.content[:800],
        flags=re.IGNORECASE,
    )
    if match:
        return format_chapter_match(match)
    return None


def format_chapter_match(match: re.Match) -> str:
    number = match.group(2)
    title = " ".join((match.group(3) or "").split()).strip(" -–—.")
    return f"Chương {number}{('. ' + title) if title else ''}"


def infer_article_label(chunk: DocumentChunk) -> str | None:
    heading_candidates = [
        *[str(item) for item in chunk.heading_path or []],
        chunk.section_name or "",
    ]
    for candidate in heading_candidates:
        match = re.search(
            r"\b(Điều|Dieu)\s+(\d+[a-zA-Z]?)\.?\s*([^\n.;:]{0,120})",
            candidate,
            flags=re.IGNORECASE,
        )
        if not match:
            continue
        return format_article_match(match)

    match = re.search(
        r"(?:^|\n)\s*(Điều|Dieu)\s+(\d+[a-zA-Z]?)\.?\s*([^\n.;:]{0,120})",
        chunk.content[:800],
        flags=re.IGNORECASE,
    )
    if match:
        return format_article_match(match)
    return None


def format_article_match(match: re.Match) -> str:
    prefix = "Điều"
    number = match.group(2)
    title = " ".join((match.group(3) or "").split()).strip(" -–—.")
    return f"{prefix} {number}{('. ' + title) if title else ''}"


def infer_section_label(
    chunk: DocumentChunk,
    chapter: str | None,
    article: str | None,
) -> str:
    if article:
        return article
    if chapter:
        return chapter
    heading_path = [str(item).strip() for item in chunk.heading_path or [] if str(item).strip()]
    if heading_path:
        return " > ".join(heading_path[-2:])
    section_name = (chunk.section_name or "").strip()
    if section_name and section_name.lower() not in {"paragraph", "body"}:
        return section_name
    numbered_section = infer_numbered_section_label(chunk)
    if numbered_section:
        return numbered_section
    if chunk.page_start is not None:
        return f"Trang {chunk.page_start}"
    return "Doan trich"


def infer_numbered_section_label(chunk: DocumentChunk) -> str | None:
    match = re.search(r"(?:^|\n)\s*(\d{1,3})[.)]\s+([^\n]{0,120})", chunk.content[:500])
    if not match:
        return None
    title = " ".join((match.group(2) or "").split()).strip(" -–—.")
    if title:
        return f"Muc {match.group(1)}. {title}"
    return f"Muc {match.group(1)}"


def build_source_label(
    document_label: str,
    chapter: str | None,
    article: str | None,
    section: str,
    page: int | None,
) -> str:
    parts = [document_label]
    if chapter:
        parts.append(chapter)
    if article and article != chapter:
        parts.append(article)
    if not chapter and not article:
        parts.append(section)
    if page is not None:
        parts.append(f"trang {page}")
    return " - ".join(part for part in parts if part)


def graph_search_available(tenant_id: str, db: Session) -> bool:
    processed_count = db.scalar(
        select(func.count(Document.id)).where(
            Document.tenant_id == tenant_id,
            Document.status == "processed",
        )
    ) or 0
    if processed_count <= 0:
        return False

    with neo4j_client.driver.session() as session:
        mention_count = session.run(
            """
            MATCH ()-[m:MENTIONED_IN]->()
            RETURN count(m) AS mention_count
            """
        ).single()
    return bool(mention_count and int(mention_count["mention_count"] or 0) > 0)


def vector_search(
    payload: QueryRequest,
    db: Session,
    subqueries: list[str],
    intent: str,
) -> list[RetrievalChunk]:
    vector_limit = max(payload.top_k * VECTOR_CANDIDATE_MULTIPLIER, VECTOR_CANDIDATE_FLOOR)
    if intent == "compare":
        vector_limit += settings.retrieval_compare_extra_k
    merged: dict[str, RetrievalChunk] = {}
    filters = build_version_filters(payload)

    for subquery in subqueries:
        query_vector = embedding_provider.embed_queries([subquery])[0]
        statement = (
            select(DocumentChunk, ChunkEmbedding, Document, DocumentVersion)
            .join(ChunkEmbedding, ChunkEmbedding.document_chunk_id == DocumentChunk.id)
            .join(Document, Document.id == DocumentChunk.document_id)
            .join(DocumentVersion, DocumentVersion.id == DocumentChunk.document_version_id)
            .where(DocumentChunk.tenant_id == payload.tenant_id, *filters)
            .order_by(ChunkEmbedding.embedding.cosine_distance(query_vector))
            .limit(vector_limit)
        )
        rows = db.execute(statement).all()
        for chunk, embedding, document, version in rows:
            score = cosine_similarity(query_vector, list(embedding.embedding))
            existing = merged.get(chunk.id)
            if existing and (existing.vector_score or 0.0) >= score:
                continue
            merged[chunk.id] = RetrievalChunk(
                chunk_id=chunk.id,
                score=score,
                content=chunk.content,
                source=build_citation(db, document, version, chunk),
                retrieval_source="vector",
                vector_score=score,
                final_score=score,
                query_path=[subquery],
            )

    return list(merged.values())


def graph_search(
    payload: QueryRequest,
    query_terms: list[str],
    db: Session,
    intent: str,
) -> list[RetrievalChunk]:
    if not query_terms:
        return []

    hops = min(3, max(1, settings.retrieval_graph_hops))
    cypher = f"""
    MATCH (seed:Entity)
    WHERE seed.tenant_id = $tenant_id
      AND any(
        term IN $terms WHERE toLower(coalesce(seed.name, seed.key, '')) CONTAINS term
        OR any(alias IN coalesce(seed.aliases, []) WHERE toLower(alias) CONTAINS term)
      )
    WITH collect(DISTINCT seed) AS seeds
    UNWIND seeds AS seed
    OPTIONAL MATCH (seed)-[:RELATED_TO*1..{hops}]-(neighbor:Entity {{tenant_id: $tenant_id}})
    WITH [item IN collect(DISTINCT seed) + collect(DISTINCT neighbor) WHERE item IS NOT NULL] AS entities
    UNWIND entities AS entity
    WITH DISTINCT entity
    MATCH (entity)-[m:MENTIONED_IN]->(d:Document {{tenant_id: $tenant_id}})
    RETURN d.id AS document_id,
           collect(DISTINCT coalesce(entity.name, entity.key)) AS supporting_entities,
           max(CASE WHEN m.confidence IS NULL THEN 0.5 ELSE m.confidence END) AS mention_confidence
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

    filters = build_version_filters(payload)
    statement = (
        select(DocumentChunk, Document, DocumentVersion)
        .join(Document, Document.id == DocumentChunk.document_id)
        .join(DocumentVersion, DocumentVersion.id == DocumentChunk.document_version_id)
        .where(
            DocumentChunk.tenant_id == payload.tenant_id,
            DocumentChunk.document_id.in_(list(doc_support.keys())),
            *filters,
        )
        .order_by(DocumentChunk.document_id.asc(), DocumentChunk.chunk_index.asc())
    )
    chunk_rows = db.execute(statement).all()

    ranked_by_document: dict[str, list[tuple[float, RetrievalChunk]]] = defaultdict(list)
    for chunk, document, version in chunk_rows:
        support = doc_support.get(document.id)
        if support is None:
            continue
        lexical_overlap = score_term_overlap(query_terms, chunk.content)
        entity_overlap = score_entity_overlap(support["supporting_entities"], chunk.content)
        graph_score = min(
            1.0,
            support["mention_confidence"] * 0.45 + lexical_overlap * 0.35 + entity_overlap * 0.20,
        )
        if intent == "temporal":
            graph_score = min(1.0, graph_score + 0.08)
        if graph_score <= 0:
            continue
        context = RetrievalChunk(
            chunk_id=chunk.id,
            score=graph_score,
            content=chunk.content,
            source=build_citation(db, document, version, chunk),
            retrieval_source="graph",
            graph_score=graph_score,
            final_score=graph_score,
            supporting_entities=support["supporting_entities"][:6],
            query_path=["graph-expansion"],
        )
        ranked_by_document[document.id].append((graph_score, context))

    results: list[RetrievalChunk] = []
    per_document_limit = 3 if intent == "compare" else 2
    for ranked_chunks in ranked_by_document.values():
        ranked_chunks.sort(key=lambda item: item[0], reverse=True)
        results.extend(context for _, context in ranked_chunks[:per_document_limit])

    return results


def merge_contexts(
    vector_contexts: list[RetrievalChunk],
    graph_contexts: list[RetrievalChunk],
    lexical_contexts: list[RetrievalChunk],
) -> list[RetrievalChunk]:
    merged: dict[str, RetrievalChunk] = {context.chunk_id: context for context in vector_contexts}

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
        final_score = min(1.0, vector_score * 0.6 + graph_score * 0.4)
        merged[context.chunk_id] = existing.model_copy(
            update={
                "score": final_score,
                "retrieval_source": "hybrid",
                "graph_score": graph_score,
                "final_score": final_score,
                "supporting_entities": merge_entities(
                    existing.supporting_entities, context.supporting_entities
                ),
                "query_path": merge_entities(existing.query_path, context.query_path),
            }
        )

    for context in lexical_contexts:
        existing = merged.get(context.chunk_id)
        if existing is None:
            merged[context.chunk_id] = context
            continue
        lexical_score = context.final_score if context.final_score is not None else context.score
        current_score = existing.final_score if existing.final_score is not None else existing.score
        boosted_score = min(1.0, current_score * 0.88 + lexical_score * 0.12)
        merged[context.chunk_id] = existing.model_copy(
            update={
                "score": boosted_score,
                "final_score": boosted_score,
                "retrieval_source": "hybrid" if existing.retrieval_source != "lexical" else "lexical",
                "query_path": merge_entities(existing.query_path, context.query_path),
            }
        )

    return list(merged.values())


def rerank_contexts(
    contexts: list[RetrievalChunk],
    query_terms: list[str],
    intent: str,
) -> list[RetrievalChunk]:
    reranked: list[RetrievalChunk] = []
    for context in contexts:
        lexical_score = score_term_overlap(query_terms, context.content)
        provenance_bonus = 0.04 if context.source.section_path else 0.0
        compare_bonus = 0.08 if intent == "compare" and len(context.query_path) > 0 else 0.0
        temporal_bonus = 0.05 if intent == "temporal" and context.source.page is not None else 0.0
        short_chunk_penalty = chunk_length_penalty(context.content)
        richness_bonus = 0.03 if len(" ".join(context.content.split())) >= 240 else 0.0
        re_rank_score = min(
            1.0,
            (context.final_score or context.score) * 0.72
            + lexical_score * 0.20
            + provenance_bonus
            + compare_bonus
            + temporal_bonus,
        )
        re_rank_score = max(0.0, re_rank_score + richness_bonus - short_chunk_penalty)
        reranked.append(
            context.model_copy(update={"re_rank_score": re_rank_score, "final_score": re_rank_score})
        )

    reranked.sort(key=lambda item: item.final_score or item.score, reverse=True)
    return reranked


def enforce_evidence_threshold(contexts: list[RetrievalChunk]) -> list[RetrievalChunk]:
    if not contexts:
        return []
    filtered = [
        context
        for context in contexts
        if (context.final_score or context.score) >= settings.retrieval_min_final_score
    ]
    return filtered


def lexical_fallback(
    payload: QueryRequest,
    db: Session,
    query_terms: list[str],
    intent: str,
    limit: int | None = None,
) -> list[RetrievalChunk]:
    if not query_terms:
        return []
    filters = build_version_filters(payload)
    candidate_limit = limit or payload.top_k
    statement = (
        select(DocumentChunk, Document, DocumentVersion)
        .join(Document, Document.id == DocumentChunk.document_id)
        .join(DocumentVersion, DocumentVersion.id == DocumentChunk.document_version_id)
        .where(
            DocumentChunk.tenant_id == payload.tenant_id,
            or_(*[DocumentChunk.content.ilike(f"%{term}%") for term in query_terms[:5]]),
            *filters,
        )
        .order_by(DocumentChunk.chunk_index.asc())
        .limit(candidate_limit + (settings.retrieval_compare_extra_k if intent == "compare" else 0))
    )
    rows = db.execute(statement).all()
    contexts = [
        RetrievalChunk(
            chunk_id=chunk.id,
            score=score_term_overlap(query_terms, chunk.content) or 0.5,
            content=chunk.content,
            source=build_citation(db, document, version, chunk),
            retrieval_source="lexical",
            final_score=score_term_overlap(query_terms, chunk.content) or 0.5,
            query_path=["lexical-fallback"],
        )
        for chunk, document, version in rows
    ]
    contexts = rerank_contexts(contexts, query_terms, intent)
    return contexts[:candidate_limit]


def merge_entities(left: list[str], right: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for item in left + right:
        normalized = item.strip()
        if not normalized or normalized.lower() in seen:
            continue
        seen.add(normalized.lower())
        merged.append(normalized)
    return merged[:10]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    numerator = sum(a * b for a, b in zip(left, right, strict=False))
    left_norm = math.sqrt(sum(value * value for value in left)) or 1.0
    right_norm = math.sqrt(sum(value * value for value in right)) or 1.0
    return max(0.0, numerator / (left_norm * right_norm))


def score_term_overlap(query_terms: list[str], content: str) -> float:
    if not query_terms:
        return 0.0
    lowered = normalize_search_text(content)
    hits = sum(1 for term in query_terms if term in lowered)
    return hits / len(query_terms)


def chunk_length_penalty(content: str) -> float:
    compact = " ".join(content.split())
    if len(compact) < SHORT_CONTEXT_CHAR_THRESHOLD:
        return 0.16
    if len(compact) < MEDIUM_CONTEXT_CHAR_THRESHOLD:
        return 0.07
    return 0.0


def score_entity_overlap(entity_names: list[str], content: str) -> float:
    if not entity_names:
        return 0.0
    lowered = content.lower()
    hits = sum(1 for entity in entity_names if entity.lower() in lowered)
    return min(1.0, hits / len(entity_names))
