"use client";

import { useEffect, useMemo, useRef, useState, useTransition } from "react";

import {
  askQuestion,
  fetchDocuments,
  rawDocumentPreviewUrl,
  type Citation,
  type ConversationTurn,
  type DocumentRecord,
  type QueryResult,
  type RetrievalContext,
} from "../lib/api";

const STORAGE_PREFIX = "tenant-chat:";
const starterPrompts = [
  "Tom tat nghia vu chinh cua doanh nghiep trong bo tai lieu nay.",
  "Cho toi checklist thuc hien theo tai lieu da nap.",
  "Neu co noi dung mau thuan giua cac tai lieu, hay chi ro giup toi.",
  "Tai lieu nay quy dinh gi ve trach nhiem cua nguoi quan ly?",
];

type ChatRole = "assistant" | "user" | "system";

type ChatMessage = {
  id: string;
  role: ChatRole;
  content: string;
  createdAt: string;
  pending?: boolean;
  answerType?: string | null;
  citations?: Citation[];
  contexts?: RetrievalContext[];
  policySummary?: string[];
  clarificationQuestion?: string | null;
  traceId?: string | null;
};

function createId() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

function createWelcomeMessage(): ChatMessage {
  return {
    id: createId(),
    role: "assistant",
    content:
      "Toi la chatbot cua tenant nay. Ban cu hoi theo ngon ngu tu nhien, toi se doc kho tri thuc da ingest va tra loi kem can cu tai lieu khi co du bang chung.",
    createdAt: new Date().toISOString(),
    answerType: "grounded",
    policySummary: ["chatbot-mode", "grounded-answer-only"],
  };
}

function buildAssistantMessage(result: QueryResult): ChatMessage {
  return {
    id: createId(),
    role: "assistant",
    content: result.answer,
    createdAt: new Date().toISOString(),
    answerType: result.answer_type,
    citations: result.citations,
    contexts: result.contexts,
    policySummary: result.policy_summary,
    clarificationQuestion: result.clarification_question ?? null,
    traceId: result.trace_id,
  };
}

function buildErrorMessage(message: string): ChatMessage {
  return {
    id: createId(),
    role: "system",
    content: `Chatbot tam thoi chua tra loi duoc. Chi tiet: ${message}`,
    createdAt: new Date().toISOString(),
    answerType: "failed",
  };
}

function answerTone(answerType?: string | null) {
  if (answerType === "grounded" || answerType === "partial") {
    return "status-ok";
  }
  if (answerType === "clarification") {
    return "status-live";
  }
  return "status-warn";
}

function answerLabel(answerType?: string | null) {
  const mapping: Record<string, string> = {
    grounded: "Co can cu",
    partial: "Mot phan",
    no_answer: "Khong du bang chung",
    refusal: "Tu choi",
    clarification: "Can lam ro",
    failed: "Can xu ly",
  };
  return mapping[answerType ?? ""] ?? "Phan hoi";
}

function compactTime(value: string) {
  return new Date(value).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
}

function historyFromMessages(messages: ChatMessage[]): ConversationTurn[] {
  return messages
    .filter(
      (message) =>
        !message.pending &&
        (message.role === "user" || message.role === "assistant") &&
        message.content.trim(),
    )
    .slice(-6)
    .map((message) => ({
      role: message.role === "user" ? "user" : "assistant",
      content: message.content,
    }));
}

function hasActiveDocuments(documents: DocumentRecord[]) {
  return documents.some(
    (document) =>
      document.status === "queued" ||
      document.status === "processing" ||
      document.processing_stage_status === "queued" ||
      document.processing_stage_status === "running",
  );
}

function knowledgeStatus(documents: DocumentRecord[]) {
  const processedCount = documents.filter((document) => document.status === "processed").length;
  const activeCount = documents.filter(
    (document) =>
      document.status === "queued" ||
      document.status === "processing" ||
      document.processing_stage_status === "queued" ||
      document.processing_stage_status === "running",
  ).length;
  const leadingDocument = [...documents]
    .filter(
      (document) =>
        document.processing_stage_status === "queued" || document.processing_stage_status === "running",
    )
    .sort((left, right) => right.processing_progress_percent - left.processing_progress_percent)[0];

  if (documents.length === 0) {
    return {
      label: "Chua co kho tri thuc",
      tone: "status-warn",
      detail: "Hay upload tai lieu truoc khi bat dau hoi dap.",
      canChat: false,
    };
  }

  if (processedCount === 0 && activeCount > 0) {
    return {
      label: "Dang xay kho tri thuc",
      tone: "status-live",
      detail:
        leadingDocument?.processing_progress_detail ??
        "Tai lieu dang duoc parse, chunk, embed va extract graph. Chatbot se on dinh hon khi co it nhat 1 tai lieu processed.",
      canChat: true,
    };
  }

  if (activeCount > 0) {
    return {
      label: "Kho tri thuc dang cap nhat",
      tone: "status-live",
      detail:
        leadingDocument
          ? `${leadingDocument.title}: ${leadingDocument.processing_progress_label.toLowerCase()} (${leadingDocument.processing_progress_percent}%).`
          : "Van co the chat, nhung mot phan noi dung moi co the chua duoc index xong.",
      canChat: true,
    };
  }

  return {
    label: "San sang hoi dap",
    tone: "status-ok",
    detail: `${processedCount} tai lieu da san sang cho chatbot khai thac.`,
    canChat: true,
  };
}

export function ChatPanel({ tenantId }: { tenantId: string }) {
  const [messages, setMessages] = useState<ChatMessage[]>([createWelcomeMessage()]);
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [draft, setDraft] = useState(starterPrompts[0]);
  const [isPending, startTransition] = useTransition();
  const threadRef = useRef<HTMLDivElement | null>(null);

  const storageKey = `${STORAGE_PREFIX}${tenantId}`;
  const status = useMemo(() => knowledgeStatus(documents), [documents]);

  const resetConversation = () => {
    const welcome = createWelcomeMessage();
    setMessages([welcome]);
    setDraft(starterPrompts[0]);
    sessionStorage.setItem(storageKey, JSON.stringify([welcome]));
  };

  const reloadDocuments = () => {
    startTransition(() => {
      void (async () => {
        const items = await fetchDocuments(tenantId);
        setDocuments(items);
      })();
    });
  };

  useEffect(() => {
    const stored = sessionStorage.getItem(storageKey);
    if (!stored) {
      setMessages([createWelcomeMessage()]);
      return;
    }
    try {
      const parsed = JSON.parse(stored) as ChatMessage[];
      setMessages(parsed.length > 0 ? parsed : [createWelcomeMessage()]);
    } catch {
      setMessages([createWelcomeMessage()]);
    }
  }, [storageKey]);

  useEffect(() => {
    const persistable = messages.filter((message) => !message.pending);
    sessionStorage.setItem(storageKey, JSON.stringify(persistable));
  }, [messages, storageKey]);

  useEffect(() => {
    reloadDocuments();
  }, [tenantId]);

  useEffect(() => {
    if (!tenantId || !hasActiveDocuments(documents)) {
      return;
    }
    const timer = window.setInterval(() => {
      reloadDocuments();
    }, 7000);
    return () => window.clearInterval(timer);
  }, [documents, tenantId]);

  useEffect(() => {
    const thread = threadRef.current;
    if (!thread) {
      return;
    }
    thread.scrollTop = thread.scrollHeight;
  }, [messages]);

  return (
    <section className="panel panel-strong chat-shell">
      <div className="panel-header">
        <div>
          <h2>Chatbot Tenant</h2>
          <p className="muted">
            Day la tro ly hoi dap theo kho tri thuc cua tenant. Nguoi dung chi can chat tu nhien, con retrieval va answer policy se chay o phia sau.
          </p>
          <div className="tenant-inline">Tenant scope: {tenantId}</div>
        </div>
        <div className="button-row compact-row">
          <div className={`pill ${status.tone}`}>{status.label}</div>
          <button className="button ghost" type="button" onClick={resetConversation}>
            Cuoc hoi moi
          </button>
        </div>
      </div>

      <div className="chat-status-banner">
        <div>
          <strong>Trang thai kho tri thuc</strong>
          <p className="muted">{status.detail}</p>
        </div>
        <div className="chat-status-stats">
          <div className="detail-card">
            <span className="meta-label">documents</span>
            <strong>{documents.length}</strong>
          </div>
          <div className="detail-card">
            <span className="meta-label">processed</span>
            <strong>{documents.filter((document) => document.status === "processed").length}</strong>
          </div>
        </div>
      </div>

      <div className="prompt-chip-row">
        {starterPrompts.map((prompt) => (
          <button
            key={prompt}
            className="prompt-chip"
            type="button"
            onClick={() => setDraft(prompt)}
          >
            {prompt}
          </button>
        ))}
      </div>

      <div className="chat-thread" ref={threadRef}>
        {messages.map((message) => (
          <article
            className={`chat-message ${message.role === "user" ? "is-user" : message.role === "system" ? "is-system" : "is-assistant"}`}
            key={message.id}
          >
            <div className={`chat-bubble ${message.role === "user" ? "is-user" : message.role === "system" ? "is-system" : ""}`}>
              <div className="chat-bubble-top">
                <strong>{message.role === "user" ? "Ban" : message.role === "assistant" ? "Chatbot" : "He thong"}</strong>
                <span className="muted">{compactTime(message.createdAt)}</span>
              </div>

              <div className="chat-body-text">{message.pending ? "Dang soan cau tra loi..." : message.content}</div>

              {message.answerType ? (
                <div className={`chat-answer-pill ${answerTone(message.answerType)}`}>
                  {answerLabel(message.answerType)}
                </div>
              ) : null}

              {message.clarificationQuestion ? (
                <div className="chat-inline-note">
                  <strong>Can lam ro</strong>
                  <p>{message.clarificationQuestion}</p>
                </div>
              ) : null}

              {message.policySummary && message.policySummary.length > 0 ? (
                <div className="chat-tag-row">
                  {message.policySummary.map((item) => (
                    <span className="chat-tag" key={item}>
                      {item}
                    </span>
                  ))}
                </div>
              ) : null}

              {message.citations && message.citations.length > 0 ? (
                <div className="chat-source-list">
                  <strong>Nguon tham chieu</strong>
                  {message.citations.map((citation) => (
                    <div className="chat-source-card" key={`${message.id}-${citation.chunk_id}`}>
                      <div>
                        <strong>{citation.title}</strong>
                        <div className="muted">
                          {citation.section || "unknown section"}
                          {citation.page ? ` | page ${citation.page}` : ""}
                        </div>
                      </div>
                      <a
                        className="button ghost"
                        href={rawDocumentPreviewUrl(citation.document_id, tenantId)}
                        rel="noreferrer"
                        target="_blank"
                      >
                        Mo tai lieu
                      </a>
                    </div>
                  ))}
                </div>
              ) : null}

              {message.contexts && message.contexts.length > 0 ? (
                <details className="chat-details">
                  <summary>Context da dung ({message.contexts.length})</summary>
                  <div className="chat-context-list">
                    {message.contexts.slice(0, 4).map((context) => (
                      <div className="context-item" key={`${message.id}-${context.chunk_id}`}>
                        <div className="context-head">
                          <strong>{context.source.title}</strong>
                          <span className="muted">
                            {context.retrieval_source} | score {context.final_score?.toFixed(3) ?? context.score.toFixed(3)}
                          </span>
                        </div>
                        <div className="muted">{context.content.slice(0, 240)}...</div>
                      </div>
                    ))}
                  </div>
                </details>
              ) : null}

              {message.traceId ? <div className="tiny muted">trace {message.traceId}</div> : null}
            </div>
          </article>
        ))}
      </div>

      <div className="chat-composer">
        <textarea
          className="textarea chat-input"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="Dat cau hoi theo ngon ngu tu nhien..."
        />

        <div className="chat-composer-footer">
          <div className="muted chat-helper-text">
            Chatbot se tu dong chon retrieval mode va tra loi theo evidence cua tenant, khong hien tham so ky thuat ra man hinh chinh.
          </div>
          <div className="button-row">
            <button
              className="button ghost"
              type="button"
              onClick={() => setDraft("")}
            >
              Xoa nhap
            </button>
            <button
              className="button"
              disabled={isPending || !draft.trim() || !status.canChat}
              type="button"
              onClick={() => {
                const question = draft.trim();
                if (!question) {
                  return;
                }
                const history = historyFromMessages(messages);
                const userMessage: ChatMessage = {
                  id: createId(),
                  role: "user",
                  content: question,
                  createdAt: new Date().toISOString(),
                };
                const pendingId = createId();
                const pendingMessage: ChatMessage = {
                  id: pendingId,
                  role: "assistant",
                  content: "",
                  createdAt: new Date().toISOString(),
                  pending: true,
                };
                setDraft("");
                setMessages((current) => [...current, userMessage, pendingMessage]);
                startTransition(() => {
                  void (async () => {
                    try {
                      const result = await askQuestion({
                        tenantId,
                        question,
                        queryMode: "auto",
                        topK: 6,
                        includeGraph: true,
                        includeSummaries: true,
                        conversationHistory: history,
                      });
                      const assistantMessage = buildAssistantMessage(result);
                      setMessages((current) =>
                        current.map((message) => (message.id === pendingId ? assistantMessage : message)),
                      );
                    } catch (error) {
                      const fallback = buildErrorMessage(
                        error instanceof Error ? error.message : "Unknown chatbot error",
                      );
                      setMessages((current) =>
                        current.map((message) => (message.id === pendingId ? fallback : message)),
                      );
                    }
                  })();
                });
              }}
            >
              {isPending ? "Chatbot dang tra loi..." : "Gui tin nhan"}
            </button>
          </div>
        </div>
      </div>
    </section>
  );
}
