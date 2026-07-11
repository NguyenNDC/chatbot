from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from enterprise_ai_core.db import get_db_session
from enterprise_ai_core.models import ChatMessage, ChatSession, Tenant
from enterprise_ai_core.schemas import (
    ChatMessageCreateRequest,
    ChatMessageItem,
    ChatMessageListResponse,
    ChatSessionCreateRequest,
    ChatSessionItem,
    ChatSessionListResponse,
    Citation,
    RetrievalChunk,
)

router = APIRouter(tags=["chat"])


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def get_active_tenant(db: Session, tenant_id: str) -> Tenant:
    tenant = db.get(Tenant, tenant_id)
    if tenant is None or tenant.status != "active":
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant


def derive_session_title(content: str) -> str:
    normalized = " ".join(content.split()).strip()
    if not normalized:
        return "Cuoc hoi moi"
    if len(normalized) <= 72:
        return normalized
    return f"{normalized[:69].rstrip()}..."


def build_session_item(db: Session, session: ChatSession) -> ChatSessionItem:
    message_count = db.scalar(
        select(func.count(ChatMessage.id)).where(ChatMessage.session_id == session.id)
    ) or 0
    return ChatSessionItem(
        id=session.id,
        tenant_id=session.tenant_id,
        title=session.title,
        status=session.status,
        message_count=int(message_count),
        last_message_at=session.last_message_at,
        last_message_preview=session.last_message_preview,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


def build_message_item(message: ChatMessage) -> ChatMessageItem:
    return ChatMessageItem(
        id=message.id,
        session_id=message.session_id,
        tenant_id=message.tenant_id,
        role=message.role,
        content=message.content,
        answer_type=message.answer_type,
        citations=[Citation.model_validate(item) for item in message.citations or []],
        contexts=[RetrievalChunk.model_validate(item) for item in message.contexts or []],
        policy_summary=list(message.policy_summary or []),
        clarification_question=message.clarification_question,
        refusal_reason=message.refusal_reason,
        trace_id=message.trace_id,
        created_at=message.created_at,
    )


def get_chat_session_for_tenant(db: Session, session_id: str, tenant_id: str) -> ChatSession:
    session = db.scalars(
        select(ChatSession).where(ChatSession.id == session_id, ChatSession.tenant_id == tenant_id)
    ).first()
    if session is None or session.status != "active":
        raise HTTPException(status_code=404, detail="Chat session not found")
    return session


def touch_session_after_message(
    db: Session,
    session: ChatSession,
    *,
    role: str,
    content: str,
    created_at: datetime,
) -> None:
    if role == "user" and session.title == "Cuoc hoi moi":
        session.title = derive_session_title(content)
    session.last_message_at = created_at
    session.last_message_preview = derive_session_title(content)
    session.updated_at = created_at
    db.add(session)


@router.get("/chat/sessions", response_model=ChatSessionListResponse)
async def list_chat_sessions(
    tenant_id: str = Query(...),
    db: Session = Depends(get_db_session),
) -> ChatSessionListResponse:
    get_active_tenant(db, tenant_id)
    sessions = list(
        db.scalars(
            select(ChatSession)
            .where(ChatSession.tenant_id == tenant_id, ChatSession.status == "active")
            .order_by(ChatSession.last_message_at.desc().nullslast(), ChatSession.created_at.desc())
        ).all()
    )
    items = [build_session_item(db, item) for item in sessions]
    return ChatSessionListResponse(items=items, total=len(items))


@router.post("/chat/sessions", response_model=ChatSessionItem, status_code=status.HTTP_201_CREATED)
async def create_chat_session(
    payload: ChatSessionCreateRequest,
    db: Session = Depends(get_db_session),
) -> ChatSessionItem:
    get_active_tenant(db, payload.tenant_id)
    session = ChatSession(
        tenant_id=payload.tenant_id,
        title=(payload.title or "Cuoc hoi moi").strip() or "Cuoc hoi moi",
        status="active",
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return build_session_item(db, session)


@router.get("/chat/sessions/{session_id}", response_model=ChatSessionItem)
async def get_chat_session(
    session_id: str,
    tenant_id: str = Query(...),
    db: Session = Depends(get_db_session),
) -> ChatSessionItem:
    get_active_tenant(db, tenant_id)
    session = get_chat_session_for_tenant(db, session_id, tenant_id)
    return build_session_item(db, session)


@router.delete("/chat/sessions/{session_id}", response_model=ChatSessionItem)
async def delete_chat_session(
    session_id: str,
    tenant_id: str = Query(...),
    db: Session = Depends(get_db_session),
) -> ChatSessionItem:
    get_active_tenant(db, tenant_id)
    session = get_chat_session_for_tenant(db, session_id, tenant_id)
    snapshot = build_session_item(db, session)
    db.query(ChatMessage).filter(ChatMessage.session_id == session.id).delete()
    db.delete(session)
    db.commit()
    return snapshot.model_copy(update={"status": "deleted"})


@router.get("/chat/sessions/{session_id}/messages", response_model=ChatMessageListResponse)
async def list_chat_messages(
    session_id: str,
    tenant_id: str = Query(...),
    limit: int = Query(default=200, ge=1, le=500),
    db: Session = Depends(get_db_session),
) -> ChatMessageListResponse:
    get_active_tenant(db, tenant_id)
    session = get_chat_session_for_tenant(db, session_id, tenant_id)
    recent_messages = list(
        db.scalars(
            select(ChatMessage)
            .where(ChatMessage.session_id == session.id, ChatMessage.tenant_id == tenant_id)
            .order_by(ChatMessage.created_at.desc())
            .limit(limit)
        ).all()
    )
    messages = list(reversed(recent_messages))
    items = [build_message_item(item) for item in messages]
    return ChatMessageListResponse(items=items, total=len(items))


@router.post("/chat/sessions/{session_id}/messages", response_model=ChatMessageItem, status_code=status.HTTP_201_CREATED)
async def create_chat_message(
    session_id: str,
    payload: ChatMessageCreateRequest,
    db: Session = Depends(get_db_session),
) -> ChatMessageItem:
    get_active_tenant(db, payload.tenant_id)
    session = get_chat_session_for_tenant(db, session_id, payload.tenant_id)
    created_at = utcnow()
    message = ChatMessage(
        session_id=session.id,
        tenant_id=payload.tenant_id,
        role=payload.role,
        content=payload.content,
        answer_type=payload.answer_type,
        citations=[item.model_dump(mode="json") for item in payload.citations],
        contexts=[item.model_dump(mode="json") for item in payload.contexts],
        policy_summary=list(payload.policy_summary),
        clarification_question=payload.clarification_question,
        refusal_reason=payload.refusal_reason,
        trace_id=payload.trace_id,
        created_at=created_at,
    )
    db.add(message)
    touch_session_after_message(
        db,
        session,
        role=payload.role,
        content=payload.content,
        created_at=created_at,
    )
    db.commit()
    db.refresh(message)
    return build_message_item(message)
