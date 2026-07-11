import re
import unicodedata
from uuid import uuid4

import httpx
from fastapi import APIRouter, Body, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response

from enterprise_ai_core.config import get_settings
from enterprise_ai_core.schemas import (
    ChatMessageCreateRequest,
    ChatMessageItem,
    ChatMessageListResponse,
    ChatSendMessageRequest,
    ChatSendMessageResponse,
    ChatSessionCreateRequest,
    ChatSessionItem,
    ChatSessionListResponse,
    ConversationTurn,
    DocumentDeleteResponse,
    DocumentListResponse,
    DocumentParsedPreviewResponse,
    DocumentReprocessRequest,
    DocumentVersionListResponse,
    GenerateAnswerResponse,
    ProcessingJobItem,
    ProcessingJobListResponse,
    QueryRequest,
    QueryResponse,
    TenantCreateRequest,
    TenantItem,
    TenantListResponse,
    UploadAcceptedResponse,
)

router = APIRouter(tags=["gateway"])
settings = get_settings()
REFERENTIAL_MARKERS = (
    "cai do",
    "cai nay",
    "van ban do",
    "noi dung do",
    "muc do",
    "muc nay",
    "the con",
    "con no",
    "it",
    "that",
    "those",
    "them",
    "what about",
)

CHAT_HISTORY_LIMIT = 12
RETRIEVAL_HISTORY_USER_TURNS = 2
RETRIEVAL_HISTORY_ASSISTANT_TURNS = 1
RETRIEVAL_TURN_CHAR_LIMIT = 280

GREETING_PATTERNS = {
    "good morning",
    "good afternoon",
    "good evening",
    "hi",
    "hello",
    "hey",
    "xin chao",
    "chao",
    "chao ban",
    "alo",
    "ban khoe khong",
    "khoe khong",
}
THANKS_PATTERNS = {
    "cam on",
    "cam on ban",
    "cam on nhe",
    "cam on nhieu",
    "thank",
    "thanks",
    "thank you",
    "ok cam on",
    "oke cam on",
}
GOODBYE_PATTERNS = {
    "tam biet",
    "bye",
    "goodbye",
    "hen gap lai",
}
ACK_PATTERNS = {
    "ok",
    "okay",
    "oke",
    "okey",
    "uh",
    "u",
    "um",
    "vang",
    "da",
    "duoc",
    "roi",
    "da hieu",
    "hieu roi",
    "dung roi",
    "chuan roi",
}
HELP_PATTERNS = {
    "help",
    "tro giup",
    "huong dan",
    "huong dan su dung",
    "toi co the hoi gi",
    "co the hoi gi",
    "ban giup duoc gi",
}
BOT_IDENTITY_PATTERNS = {
    "ban la ai",
    "may la ai",
    "ten ban la gi",
    "chatbot nay la gi",
    "ban lam duoc gi",
    "gioi thieu ban",
}
AMBIGUOUS_FOLLOWUP_PATTERNS = {
    "cai do la gi",
    "cai nay la gi",
    "noi ro hon",
    "giai thich them",
    "phan tich them",
    "vi du",
    "tiep di",
    "ke tiep",
}
FOLLOWUP_SHORT_PATTERNS = {
    "them",
    "them nua",
    "tiep",
    "tiep nua",
    "noi tiep",
    "sao",
    "tai sao",
    "vi sao",
    "the nao",
    "ra sao",
    "la sao",
    "gom gi",
}
UNSUPPORTED_PATTERNS = {
    "du bao thoi tiet",
    "thoi tiet",
    "tin tuc",
    "gia vang",
    "gia do la",
    "chung khoan",
    "bong da",
    "dat ve",
    "mua hang",
    "nau an",
    "viet tho",
    "ke chuyen cuoi",
    "tao anh",
    "ve anh",
    "viet code",
    "dich bai hat",
    "bai hat",
    "choi game",
}
KNOWLEDGE_MARKERS = {
    "tai lieu",
    "van ban",
    "nghi dinh",
    "thong tu",
    "quyet dinh",
    "luat",
    "dieu",
    "khoan",
    "chuong",
    "quy dinh",
    "nghia vu",
    "trach nhiem",
    "thu tuc",
    "quy trinh",
    "tom tat",
    "so sanh",
    "hieu luc",
    "can cu",
    "nguon",
    "trich",
    "trang",
}


def normalize_chat_text(message: str) -> str:
    normalized = unicodedata.normalize("NFD", message.lower()).replace("đ", "d")
    without_marks = "".join(
        char for char in normalized if unicodedata.category(char) != "Mn"
    )
    return " ".join(re.sub(r"[^a-z0-9\s]", " ", without_marks).split())


def token_count(normalized_message: str) -> int:
    return len([token for token in normalized_message.split() if token])


def contains_any(normalized_message: str, patterns: set[str]) -> bool:
    padded = f" {normalized_message} "
    return any(f" {pattern} " in padded for pattern in patterns)


def is_exact_or_short_match(normalized_message: str, patterns: set[str], max_tokens: int = 7) -> bool:
    return normalized_message in patterns or (
        token_count(normalized_message) <= max_tokens and contains_any(normalized_message, patterns)
    )


def has_knowledge_signal(normalized_message: str) -> bool:
    return contains_any(normalized_message, KNOWLEDGE_MARKERS)


def has_previous_assistant_answer(conversation_history: list[ConversationTurn]) -> bool:
    return any(turn.role == "assistant" and turn.content.strip() for turn in conversation_history)


def trim_history_text(content: str, limit: int = RETRIEVAL_TURN_CHAR_LIMIT) -> str:
    compact = " ".join(content.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."


def is_contextual_followup(
    normalized_message: str,
    conversation_history: list[ConversationTurn],
) -> bool:
    if not has_previous_assistant_answer(conversation_history):
        return False
    if is_exact_or_short_match(normalized_message, AMBIGUOUS_FOLLOWUP_PATTERNS, max_tokens=7):
        return True
    if contains_any(normalized_message, set(REFERENTIAL_MARKERS)):
        return True
    return (
        token_count(normalized_message) <= 4
        and (
            normalized_message in FOLLOWUP_SHORT_PATTERNS
            or contains_any(normalized_message, FOLLOWUP_SHORT_PATTERNS)
        )
    )


def classify_chat_intent(message: str, conversation_history: list[ConversationTurn]) -> str:
    normalized = normalize_chat_text(message)
    if not normalized:
        return "empty"

    if contains_any(normalized, UNSUPPORTED_PATTERNS):
        return "unsupported"
    if has_knowledge_signal(normalized) and token_count(normalized) > 4:
        return "knowledge_query"
    if is_exact_or_short_match(normalized, GREETING_PATTERNS, max_tokens=5):
        return "greeting"
    if is_exact_or_short_match(normalized, THANKS_PATTERNS, max_tokens=6):
        return "thanks"
    if is_exact_or_short_match(normalized, GOODBYE_PATTERNS, max_tokens=6):
        return "goodbye"
    if is_contextual_followup(normalized, conversation_history):
        return "knowledge_query"
    if is_exact_or_short_match(normalized, ACK_PATTERNS, max_tokens=4):
        return "ack"
    if is_exact_or_short_match(normalized, HELP_PATTERNS, max_tokens=9):
        return "help"
    if is_exact_or_short_match(normalized, BOT_IDENTITY_PATTERNS, max_tokens=8):
        return "bot_identity"
    if is_exact_or_short_match(normalized, AMBIGUOUS_FOLLOWUP_PATTERNS, max_tokens=7):
        has_previous_answer = has_previous_assistant_answer(conversation_history)
        return "knowledge_query" if has_previous_answer else "clarification"
    if has_knowledge_signal(normalized):
        return "knowledge_query"
    if token_count(normalized) <= 2:
        return "clarification"
    return "knowledge_query"


def direct_chat_reply(intent: str, tenant_id: str) -> tuple[str, str, list[str]] | None:
    replies = {
        "empty": (
            "Mình chưa thấy nội dung câu hỏi. Bạn nhập lại giúp mình nhé.",
            "clarification",
            ["direct-intent", "empty-message"],
        ),
        "greeting": (
            "Xin chào! Mình là trợ lý hỏi đáp theo kho tài liệu của tenant này. "
            "Bạn có thể hỏi mình về nội dung tài liệu, chương, điều, trang, quy trình, nghĩa vụ hoặc yêu cầu tóm tắt có nguồn tham chiếu.",
            "chitchat",
            ["direct-intent", "greeting"],
        ),
        "thanks": (
            "Rất vui được hỗ trợ bạn. Nếu cần, bạn cứ hỏi tiếp về nội dung trong kho tài liệu hoặc yêu cầu mình chỉ rõ nguồn theo tài liệu, chương, điều và trang.",
            "chitchat",
            ["direct-intent", "thanks"],
        ),
        "goodbye": (
            "Tạm biệt! Khi cần tra cứu hoặc kiểm chứng thông tin trong tài liệu, bạn cứ quay lại hỏi mình nhé.",
            "chitchat",
            ["direct-intent", "goodbye"],
        ),
        "ack": (
            "Mình sẵn sàng hỗ trợ tiếp. Bạn có thể hỏi thêm về tài liệu, yêu cầu tóm tắt, so sánh hoặc trích nguồn cụ thể.",
            "chitchat",
            ["direct-intent", "ack"],
        ),
        "help": (
            "Bạn có thể hỏi mình các việc như: tóm tắt tài liệu, tìm điều khoản liên quan, so sánh quy định, kiểm tra hiệu lực, lập checklist theo tài liệu, "
            "hoặc yêu cầu trích rõ nguồn theo tài liệu/chương/điều/trang.",
            "help",
            ["direct-intent", "help"],
        ),
        "bot_identity": (
            f"Mình là chatbot RAG cho tenant '{tenant_id}'. Mình trả lời dựa trên kho tài liệu đã upload, ưu tiên câu trả lời có căn cứ và nguồn tham chiếu rõ ràng.",
            "help",
            ["direct-intent", "bot-identity"],
        ),
        "clarification": (
            "Bạn nói rõ hơn giúp mình câu hỏi hoặc tài liệu muốn tra cứu nhé. Ví dụ: “Tóm tắt Điều 8 Luật Thủ đô” hoặc “Quy định về xây dựng văn bản thi hành là gì?”.",
            "clarification",
            ["direct-intent", "needs-clarification"],
        ),
        "unsupported": (
            "Mình được thiết kế để hỏi đáp theo kho tài liệu của tenant. Yêu cầu này có vẻ nằm ngoài phạm vi đó; bạn có thể chuyển thành câu hỏi liên quan đến tài liệu để mình hỗ trợ chính xác hơn.",
            "unsupported",
            ["direct-intent", "out-of-scope"],
        ),
    }
    return replies.get(intent)


def build_retrieval_question(payload: QueryRequest) -> str:
    question = " ".join(payload.question.split())
    lowered = question.lower()
    if not payload.conversation_history:
        return question

    should_expand = len(question) <= 80 or any(marker in lowered for marker in REFERENTIAL_MARKERS)
    if not should_expand:
        return question

    recent_user_turns = [
        turn.content.strip()
        for turn in payload.conversation_history
        if turn.role == "user" and turn.content.strip()
    ][-RETRIEVAL_HISTORY_USER_TURNS:]
    recent_assistant_turns = [
        trim_history_text(turn.content)
        for turn in payload.conversation_history
        if turn.role == "assistant" and turn.content.strip()
    ][-RETRIEVAL_HISTORY_ASSISTANT_TURNS:]

    expansion_parts = [*recent_user_turns]
    if any(marker in lowered for marker in REFERENTIAL_MARKERS):
        expansion_parts.extend(recent_assistant_turns)

    if not expansion_parts:
        return question

    return " ".join([*expansion_parts, question])


def build_conversation_history(messages: list[ChatMessageItem]) -> list[ConversationTurn]:
    turns = [
        ConversationTurn(role=message.role, content=message.content)
        for message in messages
        if message.role in {"user", "assistant"} and message.content.strip()
    ]
    return turns[-CHAT_HISTORY_LIMIT:]


async def run_query_pipeline(payload: QueryRequest) -> QueryResponse:
    trace_id = str(uuid4())
    retrieval_question = build_retrieval_question(payload)
    retrieval_payload = payload.model_copy(update={"question": retrieval_question})
    try:
        async with httpx.AsyncClient(timeout=settings.gateway_query_retrieval_timeout_seconds) as client:
            retrieval_response = await client.post(
                f"{settings.retrieval_service_url}{settings.api_prefix}/retrieve",
                json=retrieval_payload.model_dump(mode="json"),
            )
        retrieval_response.raise_for_status()
        retrieval_data = retrieval_response.json()
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="Retrieval service timed out") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Retrieval service request failed: {exc}") from exc

    try:
        async with httpx.AsyncClient(timeout=settings.gateway_query_llm_timeout_seconds) as client:
            llm_response = await client.post(
                f"{settings.llm_service_url}{settings.api_prefix}/generate",
                json={
                    "tenant_id": payload.tenant_id,
                    "question": payload.question,
                    "contexts": retrieval_data["contexts"],
                    "retrieval_plan": retrieval_data.get("plan", {}),
                    "conversation_history": [turn.model_dump(mode="json") for turn in payload.conversation_history],
                },
            )
        llm_response.raise_for_status()
        answer = GenerateAnswerResponse.model_validate(llm_response.json())
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="Chatbot answer generation timed out") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"LLM orchestration request failed: {exc}") from exc

    return QueryResponse(
        trace_id=trace_id,
        question=payload.question,
        answer=answer.answer,
        answer_type=answer.answer_type,
        citations=answer.citations,
        contexts=answer.contexts,
        policy_summary=answer.policy_summary,
        clarification_question=answer.clarification_question,
    )


async def get_chat_session_document_service(session_id: str, tenant_id: str) -> ChatSessionItem:
    async with httpx.AsyncClient(timeout=settings.gateway_service_timeout_seconds) as client:
        response = await client.get(
            f"{settings.document_service_url}{settings.api_prefix}/chat/sessions/{session_id}",
            params={"tenant_id": tenant_id},
        )
    response.raise_for_status()
    return ChatSessionItem.model_validate(response.json())


async def append_chat_message_document_service(
    session_id: str,
    payload: ChatMessageCreateRequest,
) -> ChatMessageItem:
    async with httpx.AsyncClient(timeout=settings.gateway_service_timeout_seconds) as client:
        response = await client.post(
            f"{settings.document_service_url}{settings.api_prefix}/chat/sessions/{session_id}/messages",
            json=payload.model_dump(mode="json"),
        )
    response.raise_for_status()
    return ChatMessageItem.model_validate(response.json())


@router.get("/documents", response_model=DocumentListResponse)
async def list_documents(tenant_id: str = Query(...)) -> DocumentListResponse:
    async with httpx.AsyncClient(timeout=settings.gateway_service_timeout_seconds) as client:
        response = await client.get(
            f"{settings.document_service_url}{settings.api_prefix}/documents",
            params={"tenant_id": tenant_id},
        )
    response.raise_for_status()
    return DocumentListResponse.model_validate(response.json())


@router.get("/tenants", response_model=TenantListResponse)
async def list_tenants() -> TenantListResponse:
    async with httpx.AsyncClient(timeout=settings.gateway_service_timeout_seconds) as client:
        response = await client.get(f"{settings.document_service_url}{settings.api_prefix}/tenants")
    response.raise_for_status()
    return TenantListResponse.model_validate(response.json())


@router.post("/tenants", response_model=TenantItem, status_code=201)
async def create_tenant(payload: TenantCreateRequest) -> TenantItem:
    async with httpx.AsyncClient(timeout=settings.gateway_service_timeout_seconds) as client:
        response = await client.post(
            f"{settings.document_service_url}{settings.api_prefix}/tenants",
            json=payload.model_dump(mode="json"),
        )
    response.raise_for_status()
    return TenantItem.model_validate(response.json())


@router.delete("/tenants/{tenant_id}", response_model=TenantItem)
async def delete_tenant(tenant_id: str) -> TenantItem:
    async with httpx.AsyncClient(timeout=settings.gateway_service_timeout_seconds) as client:
        response = await client.delete(
            f"{settings.document_service_url}{settings.api_prefix}/tenants/{tenant_id}"
        )
    response.raise_for_status()
    return TenantItem.model_validate(response.json())


@router.get("/documents/{document_id}/versions", response_model=DocumentVersionListResponse)
async def list_document_versions(
    document_id: str,
    tenant_id: str = Query(...),
) -> DocumentVersionListResponse:
    async with httpx.AsyncClient(timeout=settings.gateway_service_timeout_seconds) as client:
        response = await client.get(
            f"{settings.document_service_url}{settings.api_prefix}/documents/{document_id}/versions",
            params={"tenant_id": tenant_id},
        )
    response.raise_for_status()
    return DocumentVersionListResponse.model_validate(response.json())


@router.delete("/documents/{document_id}", response_model=DocumentDeleteResponse)
async def delete_document(
    document_id: str,
    tenant_id: str = Query(...),
) -> DocumentDeleteResponse:
    async with httpx.AsyncClient(timeout=settings.gateway_service_timeout_seconds) as client:
        response = await client.delete(
            f"{settings.document_service_url}{settings.api_prefix}/documents/{document_id}",
            params={"tenant_id": tenant_id},
        )
    response.raise_for_status()
    return DocumentDeleteResponse.model_validate(response.json())


@router.post("/documents/upload", response_model=UploadAcceptedResponse)
async def upload_document(
    tenant_id: str = Form(...),
    title: str = Form(...),
    tags: str = Form(default=""),
    file: UploadFile = File(...),
) -> UploadAcceptedResponse:
    payload = await file.read()
    async with httpx.AsyncClient(timeout=settings.gateway_service_timeout_seconds) as client:
        response = await client.post(
            f"{settings.document_service_url}{settings.api_prefix}/documents/upload",
            data={"tenant_id": tenant_id, "title": title, "tags": tags},
            files={
                "file": (
                    file.filename or "upload.bin",
                    payload,
                    file.content_type or "application/octet-stream",
                )
            },
        )
    response.raise_for_status()
    return UploadAcceptedResponse.model_validate(response.json())


@router.post("/documents/{document_id}/versions/upload", response_model=UploadAcceptedResponse)
async def upload_document_version(
    document_id: str,
    tenant_id: str = Form(...),
    title: str | None = Form(default=None),
    tags: str = Form(default=""),
    effective_from: str | None = Form(default=None),
    file: UploadFile = File(...),
) -> UploadAcceptedResponse:
    payload = await file.read()
    data = {"tenant_id": tenant_id, "tags": tags}
    if title is not None:
        data["title"] = title
    if effective_from is not None:
        data["effective_from"] = effective_from
    async with httpx.AsyncClient(timeout=settings.gateway_service_timeout_seconds) as client:
        response = await client.post(
            f"{settings.document_service_url}{settings.api_prefix}/documents/{document_id}/versions/upload",
            data=data,
            files={
                "file": (
                    file.filename or "upload.bin",
                    payload,
                    file.content_type or "application/octet-stream",
                )
            },
        )
    response.raise_for_status()
    return UploadAcceptedResponse.model_validate(response.json())


@router.post("/documents/{document_id}/reprocess", response_model=ProcessingJobItem)
async def reprocess_document(
    document_id: str,
    payload: DocumentReprocessRequest = Body(...),
    tenant_id: str = Query(...),
) -> ProcessingJobItem:
    async with httpx.AsyncClient(timeout=settings.gateway_service_timeout_seconds) as client:
        response = await client.post(
            f"{settings.document_service_url}{settings.api_prefix}/documents/{document_id}/reprocess",
            params={"tenant_id": tenant_id},
            json=payload.model_dump(mode="json"),
        )
    response.raise_for_status()
    return ProcessingJobItem.model_validate(response.json())


@router.get("/documents/{document_id}/preview/raw")
async def preview_raw_document(document_id: str, tenant_id: str = Query(...)) -> Response:
    async with httpx.AsyncClient(timeout=max(60, settings.gateway_service_timeout_seconds)) as client:
        response = await client.get(
            f"{settings.document_service_url}{settings.api_prefix}/documents/{document_id}/preview/raw",
            params={"tenant_id": tenant_id},
        )
    response.raise_for_status()
    headers = {}
    content_type = response.headers.get("content-type", "application/octet-stream")
    content_disposition = response.headers.get("content-disposition")
    if content_disposition:
        headers["Content-Disposition"] = content_disposition
    return Response(content=response.content, media_type=content_type, headers=headers)


@router.get("/documents/{document_id}/preview/parsed", response_model=DocumentParsedPreviewResponse)
async def preview_parsed_document(
    document_id: str,
    tenant_id: str = Query(...),
) -> DocumentParsedPreviewResponse:
    async with httpx.AsyncClient(timeout=settings.gateway_service_timeout_seconds) as client:
        response = await client.get(
            f"{settings.document_service_url}{settings.api_prefix}/documents/{document_id}/preview/parsed",
            params={"tenant_id": tenant_id},
        )
    response.raise_for_status()
    return DocumentParsedPreviewResponse.model_validate(response.json())


@router.post("/query", response_model=QueryResponse)
async def query(payload: QueryRequest) -> QueryResponse:
    return await run_query_pipeline(payload)


@router.get("/system/overview")
async def system_overview() -> dict:
    services = {
        "document_service": settings.document_service_url,
        "retrieval_service": settings.retrieval_service_url,
        "graph_service": settings.graph_service_url,
        "llm_service": settings.llm_service_url,
        "worker_service": settings.worker_service_url,
    }
    checks: dict[str, dict] = {}

    async with httpx.AsyncClient(timeout=min(10, settings.gateway_service_timeout_seconds)) as client:
        for name, base_url in services.items():
            try:
                response = await client.get(f"{base_url}/health")
                checks[name] = response.json()
            except httpx.HTTPError as exc:
                checks[name] = {"service": name, "status": "unavailable", "detail": str(exc)}

    status = "ok" if all(item.get("status") == "ok" for item in checks.values()) else "degraded"
    return {"status": status, "services": checks}


@router.get("/jobs", response_model=ProcessingJobListResponse)
async def list_jobs(tenant_id: str = Query(...)) -> ProcessingJobListResponse:
    async with httpx.AsyncClient(timeout=settings.gateway_service_timeout_seconds) as client:
        response = await client.get(
            f"{settings.worker_service_url}{settings.api_prefix}/jobs",
            params={"tenant_id": tenant_id},
        )
    response.raise_for_status()
    return ProcessingJobListResponse.model_validate(response.json())


@router.get("/jobs/{job_id}", response_model=ProcessingJobItem)
async def get_job(job_id: str, tenant_id: str = Query(...)) -> ProcessingJobItem:
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(
            f"{settings.worker_service_url}{settings.api_prefix}/jobs/{job_id}",
            params={"tenant_id": tenant_id},
        )
    response.raise_for_status()
    return ProcessingJobItem.model_validate(response.json())


@router.get("/chat/sessions", response_model=ChatSessionListResponse)
async def list_chat_sessions(tenant_id: str = Query(...)) -> ChatSessionListResponse:
    async with httpx.AsyncClient(timeout=settings.gateway_service_timeout_seconds) as client:
        response = await client.get(
            f"{settings.document_service_url}{settings.api_prefix}/chat/sessions",
            params={"tenant_id": tenant_id},
        )
    response.raise_for_status()
    return ChatSessionListResponse.model_validate(response.json())


@router.post("/chat/sessions", response_model=ChatSessionItem, status_code=201)
async def create_chat_session(payload: ChatSessionCreateRequest) -> ChatSessionItem:
    async with httpx.AsyncClient(timeout=settings.gateway_service_timeout_seconds) as client:
        response = await client.post(
            f"{settings.document_service_url}{settings.api_prefix}/chat/sessions",
            json=payload.model_dump(mode="json"),
        )
    response.raise_for_status()
    return ChatSessionItem.model_validate(response.json())


@router.get("/chat/sessions/{session_id}", response_model=ChatSessionItem)
async def get_chat_session(session_id: str, tenant_id: str = Query(...)) -> ChatSessionItem:
    return await get_chat_session_document_service(session_id, tenant_id)


@router.delete("/chat/sessions/{session_id}", response_model=ChatSessionItem)
async def delete_chat_session(session_id: str, tenant_id: str = Query(...)) -> ChatSessionItem:
    async with httpx.AsyncClient(timeout=settings.gateway_service_timeout_seconds) as client:
        response = await client.delete(
            f"{settings.document_service_url}{settings.api_prefix}/chat/sessions/{session_id}",
            params={"tenant_id": tenant_id},
        )
    response.raise_for_status()
    return ChatSessionItem.model_validate(response.json())


@router.get("/chat/sessions/{session_id}/messages", response_model=ChatMessageListResponse)
async def list_chat_messages(
    session_id: str,
    tenant_id: str = Query(...),
    limit: int = Query(default=200, ge=1, le=500),
) -> ChatMessageListResponse:
    async with httpx.AsyncClient(timeout=settings.gateway_service_timeout_seconds) as client:
        response = await client.get(
            f"{settings.document_service_url}{settings.api_prefix}/chat/sessions/{session_id}/messages",
            params={"tenant_id": tenant_id, "limit": limit},
        )
    response.raise_for_status()
    return ChatMessageListResponse.model_validate(response.json())


@router.post("/chat/sessions/{session_id}/messages", response_model=ChatSendMessageResponse)
async def send_chat_message(
    session_id: str,
    payload: ChatSendMessageRequest,
) -> ChatSendMessageResponse:
    session = await get_chat_session_document_service(session_id, payload.tenant_id)

    history_response = await list_chat_messages(
        session_id=session_id,
        tenant_id=payload.tenant_id,
        limit=CHAT_HISTORY_LIMIT * 4,
    )
    conversation_history = build_conversation_history(history_response.items)

    user_message = await append_chat_message_document_service(
        session_id,
        ChatMessageCreateRequest(
            tenant_id=payload.tenant_id,
            role="user",
            content=payload.message,
        ),
    )

    intent = classify_chat_intent(payload.message, conversation_history)
    direct_reply = direct_chat_reply(intent, payload.tenant_id)
    if direct_reply is not None:
        content, answer_type, policy_summary = direct_reply
        assistant_message = await append_chat_message_document_service(
            session_id,
            ChatMessageCreateRequest(
                tenant_id=payload.tenant_id,
                role="assistant",
                content=content,
                answer_type=answer_type,
                policy_summary=policy_summary,
            ),
        )
        updated_session = await get_chat_session_document_service(session.id, payload.tenant_id)
        return ChatSendMessageResponse(
            session=updated_session,
            user_message=user_message,
            assistant_message=assistant_message,
        )

    try:
        query_response = await run_query_pipeline(
            QueryRequest(
                tenant_id=payload.tenant_id,
                question=payload.message,
                top_k=payload.top_k,
                include_graph=payload.include_graph,
                include_summaries=payload.include_summaries,
                query_mode=payload.query_mode,
                conversation_history=conversation_history,
            )
        )
        assistant_message = await append_chat_message_document_service(
            session_id,
            ChatMessageCreateRequest(
                tenant_id=payload.tenant_id,
                role="assistant",
                content=query_response.answer,
                answer_type=query_response.answer_type.value,
                citations=query_response.citations,
                contexts=query_response.contexts,
                policy_summary=query_response.policy_summary,
                clarification_question=query_response.clarification_question,
                trace_id=query_response.trace_id,
            ),
        )
    except HTTPException as exc:
        assistant_message = await append_chat_message_document_service(
            session_id,
            ChatMessageCreateRequest(
                tenant_id=payload.tenant_id,
                role="system",
                content=f"Chatbot tam thoi chua tra loi duoc. Chi tiet: {exc.detail}",
                answer_type="failed",
                policy_summary=["delivery-failure"],
            ),
        )
    except Exception as exc:
        assistant_message = await append_chat_message_document_service(
            session_id,
            ChatMessageCreateRequest(
                tenant_id=payload.tenant_id,
                role="system",
                content=f"Chatbot tam thoi chua tra loi duoc. Chi tiet: {exc}",
                answer_type="failed",
                policy_summary=["delivery-failure"],
            ),
        )
    updated_session = await get_chat_session_document_service(session.id, payload.tenant_id)
    return ChatSendMessageResponse(
        session=updated_session,
        user_message=user_message,
        assistant_message=assistant_message,
    )
