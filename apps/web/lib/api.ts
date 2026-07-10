const apiBaseUrl =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ?? "http://localhost:8000";

export type QueryMode = "auto" | "lookup" | "summary" | "compare" | "temporal";

export type Citation = {
  document_id: string;
  document_version_id?: string | null;
  title: string;
  section: string;
  page?: number | null;
  chunk_id: string;
};

export type RetrievalContext = {
  chunk_id: string;
  score: number;
  content: string;
  retrieval_source: string;
  final_score?: number | null;
  source: Citation;
};

export type QueryResult = {
  trace_id: string;
  question: string;
  answer: string;
  answer_type: string;
  citations: Citation[];
  contexts: RetrievalContext[];
  policy_summary: string[];
  clarification_question?: string | null;
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
  current_job_type?: string | null;
  current_job_status?: string | null;
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
};

export type ServiceStatusMap = Record<string, { status: string; detail?: string }>;

async function parseJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return (await response.json()) as T;
}

export async function askQuestion({
  tenantId,
  question,
  queryMode,
  topK,
  includeGraph,
  includeSummaries,
}: {
  tenantId: string;
  question: string;
  queryMode: QueryMode;
  topK: number;
  includeGraph: boolean;
  includeSummaries: boolean;
}): Promise<QueryResult> {
  return parseJson<QueryResult>(
    await fetch(`${apiBaseUrl}/api/v1/query`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        tenant_id: tenantId,
        question,
        query_mode: queryMode,
        top_k: topK,
        include_graph: includeGraph,
        include_summaries: includeSummaries,
      }),
    }),
  );
}

export async function fetchDocuments(): Promise<DocumentRecord[]> {
  const data = await parseJson<{ items: DocumentRecord[] }>(
    await fetch(`${apiBaseUrl}/api/v1/documents`, { cache: "no-store" }),
  );
  return data.items;
}

export async function uploadDocument({
  tenantId,
  title,
  tags,
  file,
}: {
  tenantId: string;
  title: string;
  tags: string;
  file: File;
}): Promise<{ document: DocumentRecord; root_job: JobRecord; object_key: string }> {
  const formData = new FormData();
  formData.append("tenant_id", tenantId);
  formData.append("title", title);
  formData.append("tags", tags);
  formData.append("file", file);

  return parseJson<{ document: DocumentRecord; root_job: JobRecord; object_key: string }>(
    await fetch(`${apiBaseUrl}/api/v1/documents/upload`, {
      method: "POST",
      body: formData,
    }),
  );
}

export async function fetchSystemOverview(): Promise<ServiceStatusMap> {
  const data = await parseJson<{ services: ServiceStatusMap }>(
    await fetch(`${apiBaseUrl}/api/v1/system/overview`, { cache: "no-store" }),
  );
  return data.services;
}

export async function fetchJobs(): Promise<JobRecord[]> {
  const data = await parseJson<{ items: JobRecord[] }>(
    await fetch(`${apiBaseUrl}/api/v1/jobs`, { cache: "no-store" }),
  );
  return data.items;
}
