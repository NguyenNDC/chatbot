import { useEffect, useMemo, useRef, useState } from "react";
import {
  Bot,
  ExternalLink,
  MessageSquarePlus,
  RefreshCw,
  Search,
  Send,
  Trash2,
  UserRound,
} from "lucide-react";

import {
  createChatSession,
  deleteChatSession,
  fetchChatMessages,
  fetchChatSessions,
  rawDocumentPreviewUrl,
  sendChatMessage,
  type ChatMessageRecord,
  type ChatSessionRecord,
  type DocumentRecord,
} from "../lib/api";
import { cx, formatTime, initials } from "../lib/format";

const starterPrompts = [
  "Thue gia tri gia tang duoc quy dinh nhu the nao?",
  "Tom tat cac nghia vu chinh trong kho tai lieu.",
  "Cho toi checklist thuc hien theo tai lieu da nap.",
  "Neu co noi dung mau thuan giua cac tai lieu, hay chi ro.",
];

type PendingChatMessage = ChatMessageRecord & { pending?: boolean };

function createId() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

function createPendingMessages(tenantId: string, sessionId: string, content: string) {
  return {
    user: {
      id: `pending-user-${createId()}`,
      session_id: sessionId,
      tenant_id: tenantId,
      role: "user" as const,
      content,
      citations: [],
      contexts: [],
      policy_summary: [],
      created_at: new Date().toISOString(),
    },
    assistant: {
      id: `pending-assistant-${createId()}`,
      session_id: sessionId,
      tenant_id: tenantId,
      role: "assistant" as const,
      content: "",
      answer_type: "pending",
      citations: [],
      contexts: [],
      policy_summary: [],
      created_at: new Date().toISOString(),
      pending: true,
    },
  };
}

function answerLabel(answerType?: string | null) {
  const mapping: Record<string, string> = {
    grounded: "Co can cu",
    partial: "Mot phan",
    no_answer: "Khong du bang chung",
    refusal: "Tu choi",
    clarification: "Can lam ro",
    chitchat: "Tro chuyen",
    help: "Huong dan",
    unsupported: "Ngoai pham vi",
    pending: "Dang xu ly",
    failed: "Loi",
  };
  return mapping[answerType ?? ""] ?? "Tra loi";
}

function readableMessageContent(content: string) {
  const trimmed = content.trim();
  if (!trimmed) {
    return "";
  }

  const candidates = [trimmed];
  const objectStart = trimmed.indexOf("{");
  const objectEnd = trimmed.lastIndexOf("}");
  if (objectStart >= 0 && objectEnd > objectStart) {
    candidates.push(trimmed.slice(objectStart, objectEnd + 1));
  }

  for (const candidate of candidates) {
    try {
      const parsed = JSON.parse(candidate) as { answer?: unknown; content?: unknown; message?: unknown };
      const readable = parsed.answer ?? parsed.content ?? parsed.message;
      if (typeof readable === "string" && readable.trim()) {
        return readable.trim();
      }
    } catch {
      // Plain text is the common path. Keep it as-is.
    }
  }
  return content;
}

function citationLabel(citation: {
  title: string;
  section?: string | null;
  page?: number | null;
  document_label?: string | null;
  chapter?: string | null;
  article?: string | null;
  source_label?: string | null;
}) {
  if (citation.source_label?.trim()) {
    return citation.source_label.trim();
  }
  const documentLabel = citation.document_label || citation.title;
  const location = [citation.chapter, citation.article || citation.section].filter(Boolean).join(" - ") || "Không rõ chương/điều";
  const page = citation.page ? `trang ${citation.page}` : "không rõ trang";
  return `${documentLabel} - ${location} - ${page}`;
}

function citationLocation(citation: {
  section?: string | null;
  page?: number | null;
  chapter?: string | null;
  article?: string | null;
}) {
  const location = [citation.chapter, citation.article || citation.section].filter(Boolean).join(" · ") || "Không rõ chương/điều";
  const page = citation.page ? `Trang ${citation.page}` : "Không rõ trang";
  return `${location} · ${page}`;
}

function knowledgeStatus(documents: DocumentRecord[]) {
  const ready = documents.filter((document) => document.status === "processed").length;
  const active = documents.filter(
    (document) =>
      document.status === "queued" ||
      document.status === "processing" ||
      document.processing_stage_status === "queued" ||
      document.processing_stage_status === "running",
  ).length;
  if (documents.length === 0) {
    return { label: "Chua co tai lieu", tone: "danger", detail: "Upload tai lieu truoc khi hoi dap.", canChat: false };
  }
  if (ready === 0 && active > 0) {
    return { label: "Dang index", tone: "live", detail: "Co the hoi thu, ket qua se tot hon khi pipeline hoan tat.", canChat: true };
  }
  if (active > 0) {
    return { label: "Dang cap nhat", tone: "live", detail: `${ready}/${documents.length} tai lieu da san sang.`, canChat: true };
  }
  return { label: "San sang", tone: "success", detail: `${ready} tai lieu san sang cho chatbot.`, canChat: true };
}

function sessionGroups(sessions: ChatSessionRecord[], query: string) {
  const keyword = query.trim().toLowerCase();
  const filtered = sessions.filter((session) =>
    !keyword
      ? true
      : [session.title, session.last_message_preview ?? ""].join(" ").toLowerCase().includes(keyword),
  );
  return filtered.sort(
    (left, right) =>
      new Date(right.last_message_at ?? right.updated_at).getTime() -
      new Date(left.last_message_at ?? left.updated_at).getTime(),
  );
}

export function ChatPanel({ tenantId, documents }: { tenantId: string; documents: DocumentRecord[] }) {
  const [sessions, setSessions] = useState<ChatSessionRecord[]>([]);
  const [messages, setMessages] = useState<PendingChatMessage[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const threadRef = useRef<HTMLDivElement | null>(null);

  const status = useMemo(() => knowledgeStatus(documents), [documents]);
  const filteredSessions = useMemo(() => sessionGroups(sessions, query), [query, sessions]);
  const activeSession = sessions.find((session) => session.id === activeSessionId) ?? null;

  const loadMessages = async (sessionId: string) => {
    setMessages(await fetchChatMessages(sessionId, tenantId));
  };

  const loadSessions = async (preferredSessionId?: string | null) => {
    setLoading(true);
    setError(null);
    try {
      const items = await fetchChatSessions(tenantId);
      if (items.length === 0) {
        const session = await createChatSession({ tenantId, title: "Cuoc tro chuyen moi" });
        setSessions([session]);
        setActiveSessionId(session.id);
        setMessages([]);
        return;
      }
      setSessions(items);
      const nextSessionId =
        preferredSessionId && items.some((session) => session.id === preferredSessionId)
          ? preferredSessionId
          : items[0].id;
      setActiveSessionId(nextSessionId);
      await loadMessages(nextSessionId);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Cannot load chat sessions");
    } finally {
      setLoading(false);
    }
  };

  const createSession = async () => {
    setLoading(true);
    setError(null);
    try {
      const session = await createChatSession({ tenantId, title: "Cuoc tro chuyen moi" });
      const items = await fetchChatSessions(tenantId);
      setSessions(items);
      setActiveSessionId(session.id);
      setMessages([]);
      setDraft("");
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Cannot create chat session");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadSessions();
  }, [tenantId]);

  useEffect(() => {
    const thread = threadRef.current;
    if (!thread) {
      return;
    }
    thread.scrollTop = thread.scrollHeight;
  }, [messages]);

  const send = async () => {
    const question = draft.trim();
    if (!question || !activeSessionId) {
      return;
    }
    const pending = createPendingMessages(tenantId, activeSessionId, question);
    setDraft("");
    setError(null);
    setSending(true);
    setMessages((current) => [...current, pending.user, pending.assistant]);
    try {
      const response = await sendChatMessage({
        sessionId: activeSessionId,
        tenantId,
        message: question,
      });
      setMessages((current) =>
        current.map((message) => {
          if (message.id === pending.user.id) {
            return response.user_message;
          }
          if (message.id === pending.assistant.id) {
            return response.assistant_message;
          }
          return message;
        }),
      );
      setSessions(await fetchChatSessions(tenantId));
      setActiveSessionId(response.session.id);
    } catch (nextError) {
      const message = nextError instanceof Error ? nextError.message : "Cannot send message";
      setError(message);
      setMessages((current) =>
        current.map((item) =>
          item.id === pending.assistant.id
            ? {
                ...item,
                pending: false,
                role: "system",
                content: `Chatbot tam thoi chua tra loi duoc. Chi tiet: ${message}`,
                answer_type: "failed",
                policy_summary: ["delivery-failure"],
              }
            : item,
        ),
      );
    } finally {
      setSending(false);
    }
  };

  return (
    <section className="surface grid min-h-[880px] min-w-0 grid-rows-[auto_1fr] overflow-hidden rounded-lg">
      <header className="flex flex-col gap-3 border-b border-slate-200 px-4 py-3 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h2 className="text-sm font-bold">Chatbot tenant</h2>
          <div className="mt-1 text-xs text-slate-500">{status.detail}</div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className={cx(status.tone === "success" && "badge-success", status.tone === "live" && "badge-live", status.tone === "danger" && "badge-danger")}>
            {status.label}
          </span>
          <button className="btn-secondary" type="button" onClick={() => loadSessions(activeSessionId)}>
            <RefreshCw className={cx("h-4 w-4", loading && "animate-spin")} />
            Refresh
          </button>
          <button className="btn-primary" type="button" onClick={createSession}>
            <MessageSquarePlus className="h-4 w-4" />
            New
          </button>
        </div>
      </header>

      <div className="grid min-h-0 lg:grid-cols-[260px_minmax(0,1fr)]">
        <aside className="grid min-h-0 grid-rows-[auto_1fr_auto] border-b border-slate-200 bg-slate-50 lg:border-b-0 lg:border-r">
          <div className="grid gap-3 border-b border-slate-200 p-3">
            <div className="flex items-center gap-2 rounded-md border border-slate-200 bg-white px-3">
              <Search className="h-4 w-4 text-slate-400" />
              <input
                className="h-10 min-w-0 flex-1 bg-transparent text-sm outline-none"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Tim session..."
              />
            </div>
          </div>
          <div className="overflow-auto p-2 app-scrollbar">
            {filteredSessions.length === 0 ? (
              <div className="p-3 text-sm text-slate-500">Chua co session phu hop.</div>
            ) : (
              <div className="grid gap-2">
                {filteredSessions.map((session) => (
                  <button
                    className={cx(
                      "grid gap-2 rounded-md border p-3 text-left transition",
                      session.id === activeSessionId
                        ? "border-ocean-200 bg-white shadow-sm"
                        : "border-transparent hover:border-slate-200 hover:bg-white",
                    )}
                    key={session.id}
                    type="button"
                    onClick={() => {
                      setActiveSessionId(session.id);
                      void loadMessages(session.id);
                    }}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div className="truncate text-sm font-semibold">{session.title}</div>
                      <div className="text-xs text-slate-400">{formatTime(session.last_message_at ?? session.created_at)}</div>
                    </div>
                    <div className="line-clamp-2 text-xs leading-5 text-slate-500">
                      {session.last_message_preview ?? "Chua co tin nhan."}
                    </div>
                    <div className="text-xs text-slate-400">{session.message_count} messages</div>
                  </button>
                ))}
              </div>
            )}
          </div>
          <div className="flex items-center justify-between gap-2 border-t border-slate-200 p-3 text-xs text-slate-500">
            <span>{activeSession?.title ?? "No session"}</span>
            {activeSession ? (
              <button
                className="icon-btn h-8 w-8 text-red-600 hover:bg-red-50"
                title="Xoa session"
                type="button"
                onClick={async () => {
                  if (!window.confirm(`Xoa session "${activeSession.title}"?`)) {
                    return;
                  }
                  await deleteChatSession(activeSession.id, tenantId);
                  await loadSessions();
                }}
              >
                <Trash2 className="h-4 w-4" />
              </button>
            ) : null}
          </div>
        </aside>

        <div className="grid min-h-0 grid-rows-[auto_1fr_auto]">
          <div className="flex items-center justify-between gap-3 border-b border-slate-200 px-4 py-3">
            <div className="flex min-w-0 items-center gap-3">
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-ink-950 text-white">
                <Bot className="h-5 w-5" />
              </div>
              <div className="min-w-0">
                <div className="truncate text-sm font-bold">{activeSession?.title ?? "Chatbot"}</div>
                <div className="truncate text-xs text-slate-500">Hybrid retrieval, citation va answer policy</div>
              </div>
            </div>
            <span className="badge-neutral">Balanced</span>
          </div>

          <div className="overflow-auto bg-white p-4 app-scrollbar" ref={threadRef}>
            {error ? <div className="mb-4 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div> : null}
            {messages.length === 0 ? (
              <div className="grid gap-4 rounded-lg border border-dashed border-slate-200 bg-slate-50 p-5">
                <div>
                  <div className="label">New conversation</div>
                  <h3 className="mt-1 text-lg font-bold">Hoi dap theo kho tri thuc cua tenant</h3>
                </div>
                <div className="grid gap-2 md:grid-cols-2">
                  {starterPrompts.map((prompt) => (
                    <button className="rounded-md border border-slate-200 bg-white p-3 text-left text-sm leading-6 hover:border-ocean-200 hover:bg-ocean-50/40" key={prompt} type="button" onClick={() => setDraft(prompt)}>
                      {prompt}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <div className="grid gap-5">
                {messages.map((message) => (
                  <article className={cx("flex gap-3", message.role === "user" && "justify-end")} key={message.id}>
                    {message.role !== "user" ? (
                      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-slate-100 text-ink-800">
                        {message.role === "assistant" ? <Bot className="h-5 w-5" /> : <MessageSquarePlus className="h-5 w-5" />}
                      </div>
                    ) : null}
                    <div className={cx("grid max-w-[840px] gap-2", message.role === "user" && "justify-items-end")}>
                      <div className="flex items-center gap-2 text-xs text-slate-500">
                        <strong className="text-slate-700">{message.role === "user" ? "Ban" : message.role === "assistant" ? "Chatbot" : "He thong"}</strong>
                        <span>{formatTime(message.created_at)}</span>
                      </div>
                      <div
                        className={cx(
                          "grid gap-3 rounded-lg border px-4 py-3 text-sm leading-7 shadow-sm",
                          message.role === "user"
                            ? "border-ocean-200 bg-ocean-50 text-ink-950"
                            : message.role === "system"
                              ? "border-red-200 bg-red-50 text-red-800"
                              : "border-slate-200 bg-white text-ink-950",
                        )}
                      >
                        <div className="whitespace-pre-wrap">{message.pending ? "Dang soan cau tra loi..." : readableMessageContent(message.content)}</div>
                        {message.answer_type && message.answer_type !== "grounded" ? <span className="badge-neutral w-fit">{answerLabel(message.answer_type)}</span> : null}
                        {message.citations.length > 0 ? (
                          <div className="grid gap-2">
                            <div className="text-xs font-bold uppercase tracking-normal text-slate-500">Nguồn tham chiếu</div>
                            <div className="flex flex-wrap gap-2">
                              {message.citations.map((citation) => (
                                <a
                                  className="flex max-w-80 items-start gap-2 rounded-md border border-slate-200 bg-slate-50 p-2 text-xs leading-5 text-slate-700 hover:border-ocean-200 hover:bg-white"
                                  href={rawDocumentPreviewUrl(citation.document_id, tenantId)}
                                  key={`${message.id}-${citation.chunk_id}`}
                                  rel="noreferrer"
                                  target="_blank"
                                  title={citationLabel(citation)}
                                >
                                  <ExternalLink className="mt-0.5 h-3.5 w-3.5 shrink-0 text-ocean-600" />
                                  <span className="min-w-0">
                                    <strong className="block truncate">{citation.document_label || citation.title}</strong>
                                    <span className="block truncate">{citationLocation(citation)}</span>
                                  </span>
                                </a>
                              ))}
                            </div>
                          </div>
                        ) : null}
                        {message.contexts.length > 0 ? (
                          <details className="rounded-md border border-slate-200 bg-slate-50 p-3">
                            <summary className="cursor-pointer text-xs font-bold text-ocean-700">Evidence da dung ({message.contexts.length})</summary>
                            <div className="mt-3 grid gap-2">
                              {message.contexts.slice(0, 4).map((context) => (
                                <div className="rounded-md bg-white p-3 text-xs leading-5 text-slate-600" key={`${message.id}-${context.chunk_id}`}>
                                  <div className="mb-1 flex items-center justify-between gap-2">
                                    <strong className="truncate text-slate-800">{context.source.document_label || context.source.title}</strong>
                                    <span>{context.final_score?.toFixed(3) ?? context.score.toFixed(3)}</span>
                                  </div>
                                  <div className="mb-1 text-slate-500">{citationLocation(context.source)}</div>
                                  {context.content.slice(0, 260)}...
                                </div>
                              ))}
                            </div>
                          </details>
                        ) : null}
                      </div>
                    </div>
                    {message.role === "user" ? (
                      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-ocean-600 text-white">
                        <UserRound className="h-5 w-5" />
                      </div>
                    ) : null}
                  </article>
                ))}
              </div>
            )}
          </div>

          <div className="border-t border-slate-200 bg-slate-50 p-3">
            <div className="mb-2 flex gap-2 overflow-auto pb-1 app-scrollbar">
              {starterPrompts.map((prompt) => (
                <button className="shrink-0 rounded-md border border-slate-200 bg-white px-3 py-2 text-xs text-slate-600 hover:border-ocean-200" key={prompt} type="button" onClick={() => setDraft(prompt)}>
                  {prompt}
                </button>
              ))}
            </div>
            <div className="grid gap-2 rounded-lg border border-slate-200 bg-white p-3">
              <textarea
                className="min-h-20 resize-none bg-transparent text-sm leading-6 outline-none"
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                placeholder="Nhap cau hoi cua ban..."
                onKeyDown={(event) => {
                  if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
                    void send();
                  }
                }}
              />
              <div className="flex items-center justify-between gap-3">
                <div className="text-xs text-slate-500">{activeSession ? `${initials(activeSession.title)} session` : "No session"}</div>
                <button className="btn-primary" disabled={sending || !draft.trim() || !status.canChat || !activeSessionId} type="button" onClick={() => void send()}>
                  <Send className="h-4 w-4" />
                  {sending ? "Dang gui" : "Gui"}
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
