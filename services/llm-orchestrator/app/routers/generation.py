from uuid import uuid4

from fastapi import APIRouter

from enterprise_ai_core.config import get_settings
from enterprise_ai_core.openrouter import OpenRouterClient
from enterprise_ai_core.prompting import (
    CLARIFICATION_TEMPLATE,
    NO_ANSWER_TEMPLATE,
    REFUSAL_TEMPLATE,
    build_answer_messages,
)
from enterprise_ai_core.schemas import (
    AnswerDisposition,
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
                "answer_type": {
                    "type": "string",
                    "enum": ["grounded", "partial", "no_answer", "refusal", "clarification"],
                },
                "answer": {"type": "string"},
                "citations": {"type": "array", "items": {"type": "string"}},
                "policy_summary": {"type": "array", "items": {"type": "string"}},
                "clarification_question": {"type": ["string", "null"]},
                "refusal_reason": {"type": ["string", "null"]},
            },
            "required": [
                "answer_type",
                "answer",
                "citations",
                "policy_summary",
                "clarification_question",
                "refusal_reason",
            ],
        },
    },
}

PROMPT_INJECTION_MARKERS = {
    "ignore previous",
    "ignore all previous",
    "system prompt",
    "developer message",
    "bypass",
    "reveal prompt",
}


@router.post("/generate", response_model=GenerateAnswerResponse)
async def generate_answer(payload: GenerateAnswerRequest) -> GenerateAnswerResponse:
    if is_prompt_injection_attempt(payload.question):
        return GenerateAnswerResponse(
            trace_id=str(uuid4()),
            model="policy-refusal",
            answer=REFUSAL_TEMPLATE,
            answer_type=AnswerDisposition.REFUSAL,
            citations=[],
            policy_summary=["refusal", "prompt-injection-protection", "grounding-policy"],
            refusal_reason="prompt_injection_suspected",
        )

    if not payload.contexts:
        return GenerateAnswerResponse(
            trace_id=str(uuid4()),
            model="no-context",
            answer=NO_ANSWER_TEMPLATE,
            answer_type=AnswerDisposition.NO_ANSWER,
            citations=[],
            policy_summary=["no-answer", "grounded-answer-only", "cite-source-required"],
        )

    selected_contexts = select_contexts(payload.contexts)
    if needs_clarification(payload, selected_contexts):
        return GenerateAnswerResponse(
            trace_id=str(uuid4()),
            model="clarification-policy",
            answer=CLARIFICATION_TEMPLATE,
            answer_type=AnswerDisposition.CLARIFICATION,
            citations=[],
            policy_summary=["clarification", "needs-more-context", "grounded-answer-only"],
            clarification_question=build_clarification_question(payload.question),
        )

    citation_map = {item.chunk_id: item.source for item in selected_contexts}
    messages = build_answer_messages(
        payload.question,
        selected_contexts,
        payload.retrieval_plan,
        payload.conversation_history,
    )
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
            answer_type=fallback["answer_type"],
            citations=fallback["citations"],
            policy_summary=fallback["policy_summary"],
        )

    citation_ids = [item for item in answer_payload.get("citations", []) if item in citation_map]
    citations = [citation_map[item] for item in citation_ids]
    disposition = parse_disposition(answer_payload.get("answer_type"))
    answer_text = str(answer_payload.get("answer", "")).strip()

    if disposition in {AnswerDisposition.GROUNDED, AnswerDisposition.PARTIAL} and not citations:
        citations = [selected_contexts[0].source]
    if not answer_text:
        answer_text = fallback_text_for(disposition)

    policy_summary = dedupe_strings(
        [str(item).strip() for item in answer_payload.get("policy_summary", []) if str(item).strip()]
    )
    if not policy_summary:
        policy_summary = default_policy_summary(disposition)

    clarification_question = normalize_optional_text(answer_payload.get("clarification_question"))
    refusal_reason = normalize_optional_text(answer_payload.get("refusal_reason"))

    return GenerateAnswerResponse(
        trace_id=str(uuid4()),
        model=model_name,
        answer=answer_text,
        answer_type=disposition,
        citations=citations,
        policy_summary=policy_summary,
        clarification_question=clarification_question,
        refusal_reason=refusal_reason,
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


def needs_clarification(payload: GenerateAnswerRequest, contexts: list[RetrievalChunk]) -> bool:
    intent = str(payload.retrieval_plan.get("intent", "lookup"))
    if intent != "compare":
        return False
    distinct_documents = {context.source.document_id for context in contexts}
    return len(distinct_documents) < 2


def build_clarification_question(question: str) -> str:
    return (
        f"Cau hoi '{question}' can chi ro hai tai lieu, hai chinh sach hoac hai phien ban can so sanh."
    )


def is_prompt_injection_attempt(question: str) -> bool:
    lowered = question.lower()
    return any(marker in lowered for marker in PROMPT_INJECTION_MARKERS)


def parse_disposition(raw_value: object) -> AnswerDisposition:
    if isinstance(raw_value, str):
        try:
            return AnswerDisposition(raw_value)
        except ValueError:
            return AnswerDisposition.GROUNDED
    return AnswerDisposition.GROUNDED


def build_local_fallback(
    question: str,
    contexts: list[RetrievalChunk],
) -> dict[str, object]:
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
        "answer_type": AnswerDisposition.PARTIAL,
        "citations": citations,
        "policy_summary": ["local-fallback", "grounded-answer-only", "cite-source-required"],
    }


def fallback_text_for(disposition: AnswerDisposition) -> str:
    if disposition == AnswerDisposition.NO_ANSWER:
        return NO_ANSWER_TEMPLATE
    if disposition == AnswerDisposition.REFUSAL:
        return REFUSAL_TEMPLATE
    if disposition == AnswerDisposition.CLARIFICATION:
        return CLARIFICATION_TEMPLATE
    return "Khong tao duoc cau tra loi co cau truc tu model."


def default_policy_summary(disposition: AnswerDisposition) -> list[str]:
    mapping = {
        AnswerDisposition.GROUNDED: ["grounded-answer-only", "cite-source-required"],
        AnswerDisposition.PARTIAL: ["partial-answer", "grounded-answer-only"],
        AnswerDisposition.NO_ANSWER: ["no-answer", "grounded-answer-only"],
        AnswerDisposition.REFUSAL: ["refusal", "policy-precedence"],
        AnswerDisposition.CLARIFICATION: ["clarification", "needs-more-context"],
    }
    return mapping[disposition]


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


def normalize_optional_text(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None
