const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000").replace(/\/$/, "");

export type QueryMode = "auto" | "lookup" | "summary" | "compare" | "temporal";

export type TenantRecord = {
  id: string;
  display_name: string;
  description?: string | null;
  status: string;
  document_count: number;
  created_at: string;
};

export type Citation = {
  document_id: string;
  document_version_id?: string | null;
  title: string;
  file_name?: string | null;
  section: string;
  section_path?: string[];
  page?: number | null;
  chunk_id: string;
  block_id?: string | null;
  document_label?: string | null;
  chapter?: string | null;
  article?: string | null;
  source_label?: string | null;
};

export type RetrievalContext = {
  chunk_id: string;
  score: number;
  content: string;
  retrieval_source: string;
  final_score?: number | null;
  source: Citation;
};

export type ParsedPreview = {
  document_id: string;
  document_version_id: string;
  version_label: string;
  title: string;
  language: string;
  ocr_required: boolean;
  ocr_applied: boolean;
  parse_quality_score: number;
  parse_warnings: string[];
  plain_text: string;
};

export type DocumentRecord = {
  id: string;
  tenant_id: string;
  title: string;
  file_name: string;
  content_type: string;
  status: string;
  version: string;
  tags?: string[];
  checksum_sha256?: string | null;
  size_bytes?: number | null;
  current_job_id?: string | null;
  current_job_type?: string | null;
  current_job_status?: string | null;
  current_job_error_message?: string | null;
  processing_stage?: string | null;
  processing_stage_label?: string | null;
  processing_stage_status?: string | null;
  processing_progress_percent: number;
  processing_progress_current?: number | null;
  processing_progress_total?: number | null;
  processing_progress_label: string;
  processing_progress_detail?: string | null;
  processing_mode?: string | null;
  created_at: string;
};

export type JobRecord = {
  id: string;
  tenant_id: string;
  document_id: string;
  job_type: string;
  queue_name: string;
  status: string;
  attempts: number;
  error_message?: string | null;
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
  parent_job_id?: string | null;
  stage_label?: string | null;
  version_label?: string | null;
  processing_mode?: string | null;
  progress_percent: number;
  progress_current?: number | null;
  progress_total?: number | null;
  progress_label: string;
  progress_detail?: string | null;
};

export type ChatSessionRecord = {
  id: string;
  tenant_id: string;
  title: string;
  status: string;
  message_count: number;
  last_message_at?: string | null;
  last_message_preview?: string | null;
  created_at: string;
  updated_at: string;
};

export type ChatMessageRecord = {
  id: string;
  session_id: string;
  tenant_id: string;
  role: "user" | "assistant" | "system";
  content: string;
  answer_type?: string | null;
  citations: Citation[];
  contexts: RetrievalContext[];
  policy_summary: string[];
  clarification_question?: string | null;
  refusal_reason?: string | null;
  trace_id?: string | null;
  created_at: string;
};

export type ChatSendResponse = {
  session: ChatSessionRecord;
  user_message: ChatMessageRecord;
  assistant_message: ChatMessageRecord;
};

export type ServiceStatusMap = Record<string, { status: string; detail?: string }>;

async function parseJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let message = `Request failed: ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: string | { message?: string } };
      if (typeof payload.detail === "string") {
        message = payload.detail;
      } else if (payload.detail?.message) {
        message = payload.detail.message;
      }
    } catch {
      // Keep the HTTP fallback message.
    }
    throw new Error(message);
  }
  return (await response.json()) as T;
}

export async function fetchTenants(): Promise<TenantRecord[]> {
  const data = await parseJson<{ items: TenantRecord[] }>(
    await fetch(`${apiBaseUrl}/api/v1/tenants`, { cache: "no-store" }),
  );
  return data.items;
}

export async function createTenant(payload: {
  id: string;
  displayName: string;
  description: string;
}): Promise<TenantRecord> {
  return parseJson<TenantRecord>(
    await fetch(`${apiBaseUrl}/api/v1/tenants`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        id: payload.id,
        display_name: payload.displayName,
        description: payload.description || null,
      }),
    }),
  );
}

export async function deleteTenant(tenantId: string): Promise<TenantRecord> {
  return parseJson<TenantRecord>(
    await fetch(`${apiBaseUrl}/api/v1/tenants/${encodeURIComponent(tenantId)}`, {
      method: "DELETE",
    }),
  );
}

export async function fetchDocuments(tenantId: string): Promise<DocumentRecord[]> {
  const data = await parseJson<{ items: DocumentRecord[] }>(
    await fetch(`${apiBaseUrl}/api/v1/documents?tenant_id=${encodeURIComponent(tenantId)}`, {
      cache: "no-store",
    }),
  );
  return data.items;
}

export async function uploadDocument(payload: {
  tenantId: string;
  title: string;
  tags: string;
  file: File;
}): Promise<{ document: DocumentRecord; root_job: JobRecord; object_key: string }> {
  const formData = new FormData();
  formData.append("tenant_id", payload.tenantId);
  formData.append("title", payload.title);
  formData.append("tags", payload.tags);
  formData.append("file", payload.file);

  return parseJson<{ document: DocumentRecord; root_job: JobRecord; object_key: string }>(
    await fetch(`${apiBaseUrl}/api/v1/documents/upload`, {
      method: "POST",
      body: formData,
    }),
  );
}

export async function deleteDocument(documentId: string, tenantId: string): Promise<{ deleted: boolean; title: string }> {
  return parseJson<{ deleted: boolean; title: string }>(
    await fetch(
      `${apiBaseUrl}/api/v1/documents/${encodeURIComponent(documentId)}?tenant_id=${encodeURIComponent(tenantId)}`,
      { method: "DELETE" },
    ),
  );
}

export async function reprocessDocument(documentId: string, tenantId: string, mode: "full" | "incremental"): Promise<JobRecord> {
  return parseJson<JobRecord>(
    await fetch(
      `${apiBaseUrl}/api/v1/documents/${encodeURIComponent(documentId)}/reprocess?tenant_id=${encodeURIComponent(tenantId)}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode, reason: "ui_reprocess" }),
      },
    ),
  );
}

export function rawDocumentPreviewUrl(documentId: string, tenantId: string): string {
  return `${apiBaseUrl}/api/v1/documents/${encodeURIComponent(documentId)}/preview/raw?tenant_id=${encodeURIComponent(tenantId)}`;
}

export async function fetchParsedPreview(documentId: string, tenantId: string): Promise<ParsedPreview> {
  return parseJson<ParsedPreview>(
    await fetch(
      `${apiBaseUrl}/api/v1/documents/${encodeURIComponent(documentId)}/preview/parsed?tenant_id=${encodeURIComponent(tenantId)}`,
      { cache: "no-store" },
    ),
  );
}

export async function fetchJobs(tenantId: string): Promise<JobRecord[]> {
  const data = await parseJson<{ items: JobRecord[] }>(
    await fetch(`${apiBaseUrl}/api/v1/jobs?tenant_id=${encodeURIComponent(tenantId)}`, {
      cache: "no-store",
    }),
  );
  return data.items;
}

export async function fetchSystemOverview(): Promise<ServiceStatusMap> {
  const data = await parseJson<{ services: ServiceStatusMap }>(
    await fetch(`${apiBaseUrl}/api/v1/system/overview`, { cache: "no-store" }),
  );
  return data.services;
}

export async function fetchChatSessions(tenantId: string): Promise<ChatSessionRecord[]> {
  const data = await parseJson<{ items: ChatSessionRecord[] }>(
    await fetch(`${apiBaseUrl}/api/v1/chat/sessions?tenant_id=${encodeURIComponent(tenantId)}`, {
      cache: "no-store",
    }),
  );
  return data.items;
}

export async function createChatSession(payload: {
  tenantId: string;
  title?: string;
}): Promise<ChatSessionRecord> {
  return parseJson<ChatSessionRecord>(
    await fetch(`${apiBaseUrl}/api/v1/chat/sessions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        tenant_id: payload.tenantId,
        title: payload.title ?? null,
      }),
    }),
  );
}

export async function deleteChatSession(sessionId: string, tenantId: string): Promise<ChatSessionRecord> {
  return parseJson<ChatSessionRecord>(
    await fetch(
      `${apiBaseUrl}/api/v1/chat/sessions/${encodeURIComponent(sessionId)}?tenant_id=${encodeURIComponent(tenantId)}`,
      { method: "DELETE" },
    ),
  );
}

export async function fetchChatMessages(sessionId: string, tenantId: string): Promise<ChatMessageRecord[]> {
  const data = await parseJson<{ items: ChatMessageRecord[] }>(
    await fetch(
      `${apiBaseUrl}/api/v1/chat/sessions/${encodeURIComponent(sessionId)}/messages?tenant_id=${encodeURIComponent(tenantId)}`,
      { cache: "no-store" },
    ),
  );
  return data.items;
}

export async function sendChatMessage(payload: {
  sessionId: string;
  tenantId: string;
  message: string;
}): Promise<ChatSendResponse> {
  return parseJson<ChatSendResponse>(
    await fetch(`${apiBaseUrl}/api/v1/chat/sessions/${encodeURIComponent(payload.sessionId)}/messages`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        tenant_id: payload.tenantId,
        message: payload.message,
        query_mode: "auto",
        top_k: 6,
        include_graph: true,
        include_summaries: true,
      }),
    }),
  );
}
