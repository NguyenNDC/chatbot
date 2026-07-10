from uuid import uuid4

from fastapi import APIRouter

from enterprise_ai_core.config import get_settings
from enterprise_ai_core.openrouter import OpenRouterClient
from enterprise_ai_core.schemas import (
    Citation,
    GenerateAnswerRequest,
    GenerateAnswerResponse,
    RetrievalChunk,
)

router = APIRouter(tags=["generation"])
settings = get_settings()
openrouter_client = OpenRouterClient()

ANSWER_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "grounded_answer",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "answer": {"type": "string"},
                "citations": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "policy_summary": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "needs_more_context": {"type": "boolean"},
            },
            "required": ["answer", "citations", "policy_summary", "needs_more_context"],
        },
    },
}


@router.post("/generate", response_model=GenerateAnswerResponse)
async def generate_answer(payload: GenerateAnswerRequest) -> GenerateAnswerResponse:
    if not payload.contexts:
        return GenerateAnswerResponse(
            trace_id=str(uuid4()),
            model="no-context",
            answer=(
                "Khong tim thay context phu hop trong tai lieu da nap, nen he thong khong the "
                "dua ra cau tra loi co grounding."
            ),
            citations=[],
            policy_summary=["no-answer", "grounded-answer-only", "cite-source-required"],
        )

    selected_contexts = select_contexts(payload.contexts)
    citation_map = {item.chunk_id: item.source for item in selected_contexts}
    context_block = render_context_block(selected_contexts)
    messages = build_messages(payload.question, context_block)

    model_name = settings.openrouter_model_primary
    answer_payload: dict | None = None
    for candidate_model in choose_models():
        try:
            result = openrouter_client.chat_completion(
                model=candidate_model,
                messages=messages,
                response_format=ANSWER_RESPONSE_FORMAT,
                temperature=0.1,
                max_tokens=settings.llm_answer_max_tokens,
            )
            answer_payload = result["content"] if isinstance(result["content"], dict) else None
            model_name = candidate_model
            if answer_payload:
                break
        except Exception:
            continue

    if not answer_payload:
        fallback = build_local_fallback(payload.question, selected_contexts)
        return GenerateAnswerResponse(
            trace_id=str(uuid4()),
            model="local-grounded-fallback",
            answer=fallback["answer"],
            citations=fallback["citations"],
            policy_summary=fallback["policy_summary"],
        )

    answer_text = str(answer_payload.get("answer", "")).strip()
    citation_ids = [item for item in answer_payload.get("citations", []) if item in citation_map]
    citations = [citation_map[item] for item in citation_ids]
    if not citations and selected_contexts:
        citations = [selected_contexts[0].source]
    if not answer_text:
        fallback = build_local_fallback(payload.question, selected_contexts)
        answer_text = fallback["answer"]
        citations = fallback["citations"]

    policy_summary = [
        str(item).strip()
        for item in answer_payload.get("policy_summary", [])
        if str(item).strip()
    ]
    if not policy_summary:
        policy_summary = ["grounded-answer-only", "cite-source-required"]
    if answer_payload.get("needs_more_context"):
        policy_summary.append("needs-more-context")

    return GenerateAnswerResponse(
        trace_id=str(uuid4()),
        model=model_name,
        answer=answer_text,
        citations=citations,
        policy_summary=dedupe_strings(policy_summary),
    )


def choose_models() -> list[str]:
    models = [settings.openrouter_model_primary]
    if settings.openrouter_model_fallback and settings.openrouter_model_fallback not in models:
        models.append(settings.openrouter_model_fallback)
    return models


def select_contexts(contexts: list[RetrievalChunk]) -> list[RetrievalChunk]:
    budget = settings.llm_context_char_budget
    selected: list[RetrievalChunk] = []
    used_chars = 0
    seen_chunks: set[str] = set()

    ranked = sorted(contexts, key=lambda item: item.final_score or item.score, reverse=True)
    for context in ranked:
        if context.chunk_id in seen_chunks:
            continue
        chunk_chars = len(context.content)
        if selected and used_chars + chunk_chars > budget:
            continue
        selected.append(context)
        used_chars += chunk_chars
        seen_chunks.add(context.chunk_id)
        if len(selected) >= settings.llm_context_max_chunks or used_chars >= budget:
            break

    return selected or ranked[:1]


def render_context_block(contexts: list[RetrievalChunk]) -> str:
    sections: list[str] = []
    for index, context in enumerate(contexts, start=1):
        supporting_entities = (
            f"\nSupporting entities: {', '.join(context.supporting_entities)}"
            if context.supporting_entities
            else ""
        )
        sections.append(
            "\n".join(
                [
                    f"[Context {index}]",
                    f"Chunk ID: {context.chunk_id}",
                    f"Document ID: {context.source.document_id}",
                    f"Document Version: {context.source.document_version_id or 'unknown'}",
                    f"Title: {context.source.title}",
                    f"Section: {context.source.section}",
                    f"Page: {context.source.page or 'n/a'}",
                    f"Retrieval source: {context.retrieval_source}",
                    f"Score: {context.final_score or context.score:.4f}{supporting_entities}",
                    f"Content:\n{context.content}",
                ]
            )
        )
    return "\n\n".join(sections)


def build_messages(question: str, context_block: str) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "You are a grounded enterprise assistant. Answer only from the provided contexts. "
                "If the contexts are insufficient, say so clearly. Keep the answer concise, "
                "cite chunk IDs that directly support the answer, and avoid inventing policies."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Question:\n{question}\n\n"
                "Use only the contexts below. Return a structured grounded answer.\n\n"
                f"{context_block}"
            ),
        },
    ]


def build_local_fallback(
    question: str,
    contexts: list[RetrievalChunk],
) -> dict[str, str | list[str] | list[Citation]]:
    top_contexts = contexts[:2]
    citations = [context.source for context in top_contexts]
    snippets = [trim_snippet(context.content) for context in top_contexts]
    answer = (
        f"Chua sinh duoc cau tra loi tu model cho cau hoi '{question}'. "
        "Duoi day la noi dung lien quan nhat tim duoc tu tai lieu: "
        + " ".join(snippets)
    )
    return {
        "answer": answer,
        "citations": citations,
        "policy_summary": [
            "local-fallback",
            "grounded-answer-only",
            "cite-source-required",
        ],
    }


def trim_snippet(content: str, limit: int = 220) -> str:
    compact = " ".join(content.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."


def dedupe_strings(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped
