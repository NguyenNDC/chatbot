import { FormEvent, useEffect, useId, useMemo, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Eye,
  FileText,
  Loader2,
  RefreshCw,
  RotateCw,
  Trash2,
  UploadCloud,
  X,
} from "lucide-react";

import {
  deleteDocument,
  fetchDocuments,
  fetchJobs,
  fetchChunkPreview,
  fetchParsedPreview,
  rawDocumentPreviewUrl,
  reprocessDocument,
  uploadDocument,
  type DocumentChunkPreview,
  type DocumentRecord,
  type JobRecord,
  type ParsedPreview,
} from "../lib/api";
import { cx, formatBytes, formatDateTime, progressCounter, statusTone } from "../lib/format";

type PreviewTab = "raw" | "parsed" | "chunks";

type PreviewState = {
  document: DocumentRecord;
  activeTab: PreviewTab;
  parsed?: ParsedPreview;
  parsedLoading?: boolean;
  parsedError?: string;
  chunks?: DocumentChunkPreview;
  chunksLoading?: boolean;
  chunksError?: string;
};

function previewTitle(document: DocumentRecord) {
  return document.content_type?.includes("pdf")
    ? "PDF goc"
    : document.content_type?.startsWith("image/")
      ? "Anh goc"
      : "Tai lieu goc";
}

function renderRawPreview(document: DocumentRecord, tenantId: string) {
  const url = rawDocumentPreviewUrl(document.id, tenantId);
  const contentType = document.content_type?.toLowerCase() ?? "";

  if (contentType.startsWith("image/")) {
    return (
      <div className="flex min-h-[78vh] items-center justify-center rounded-md border border-slate-200 bg-slate-900/95 p-4">
        <img alt={document.title} className="max-h-[74vh] max-w-full rounded-md object-contain shadow-lg" src={url} />
      </div>
    );
  }

  if (contentType.includes("pdf")) {
    return (
      <object className="h-full min-h-[78vh] w-full rounded-md border border-slate-200 bg-white" data={url} type={document.content_type}>
        <iframe className="h-full min-h-[78vh] w-full rounded-md border border-slate-200 bg-white" src={url} title={document.title} />
      </object>
    );
  }

  if (
    contentType.startsWith("text/") ||
    contentType.includes("json") ||
    contentType.includes("xml") ||
    contentType.includes("html")
  ) {
    return (
      <iframe className="h-full min-h-[78vh] w-full rounded-md border border-slate-200 bg-white" src={url} title={document.title} />
    );
  }

  return (
    <div className="grid gap-3 rounded-lg border border-slate-200 bg-white p-5 text-sm text-slate-600">
      <div className="font-semibold text-slate-800">Trinh duyet khong preview on-screen tot cho dinh dang nay.</div>
      <div>
        Tai lieu goc van duoc mo qua endpoint inline. Voi mot so dinh dang nhu `docx`, `xlsx`, `pptx`, trinh duyet co the tu dong tai file thay vi render.
      </div>
      <a
        className="btn-secondary w-fit"
        href={url}
        rel="noreferrer"
        target="_blank"
      >
        <Eye className="h-4 w-4" />
        Mo tai lieu goc
      </a>
    </div>
  );
}

function StageBadge({ status }: { status?: string | null }) {
  const tone = statusTone(status);
  return (
    <span
      className={cx(
        "shrink-0",
        tone === "success" && "badge-success",
        tone === "live" && "badge-live",
        tone === "danger" && "badge-danger",
      )}
    >
      {tone === "success" ? <CheckCircle2 className="h-3.5 w-3.5" /> : tone === "live" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <AlertTriangle className="h-3.5 w-3.5" />}
      {status ?? "unknown"}
    </span>
  );
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

function ProgressBar({ document }: { document: DocumentRecord }) {
  const counter = progressCounter(document.processing_progress_current, document.processing_progress_total);
  return (
    <div className="grid gap-2">
      <div className="flex items-center justify-between gap-3 text-xs">
        <span className="font-semibold text-slate-600">
          {document.processing_progress_label || document.processing_stage_label || "Pipeline"}
        </span>
        <span className="font-mono text-slate-500">
          {document.processing_progress_percent}%{counter ? ` | ${counter}` : ""}
        </span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-slate-100">
        <div
          className={cx(
            "h-full rounded-full transition-all",
            statusTone(document.processing_stage_status ?? document.status) === "success" && "bg-leaf-500",
            statusTone(document.processing_stage_status ?? document.status) === "live" && "bg-signal-500",
            statusTone(document.processing_stage_status ?? document.status) === "danger" && "bg-red-500",
          )}
          style={{ width: `${Math.max(2, document.processing_progress_percent)}%` }}
        />
      </div>
      {document.processing_progress_detail ? (
        <div className="text-xs leading-5 text-slate-500">{document.processing_progress_detail}</div>
      ) : null}
    </div>
  );
}

export function DocumentPanel({
  tenantId,
  documents,
  onDocumentsChange,
}: {
  tenantId: string;
  documents: DocumentRecord[];
  onDocumentsChange: (documents: DocumentRecord[]) => void;
}) {
  const [title, setTitle] = useState("");
  const [tags, setTags] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [jobs, setJobs] = useState<JobRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [preview, setPreview] = useState<PreviewState | null>(null);
  const fileInputId = useId();

  const readyCount = useMemo(() => documents.filter((document) => document.status === "processed").length, [documents]);

  const loadDocuments = async () => {
    const items = await fetchDocuments(tenantId);
    onDocumentsChange(items);
    return items;
  };

  const load = async () => {
    setLoading(true);
    setMessage(null);
    try {
      const [nextJobs] = await Promise.all([fetchJobs(tenantId), loadDocuments()]);
      setJobs(nextJobs);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Cannot load documents");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, [tenantId]);

  useEffect(() => {
    if (!hasActiveDocuments(documents)) {
      return;
    }
    const timer = window.setInterval(() => {
      void load();
    }, 3000);
    return () => window.clearInterval(timer);
  }, [documents, tenantId]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!file) {
      setMessage("Can chon file truoc khi upload.");
      return;
    }
    setLoading(true);
    setMessage(null);
    try {
      const response = await uploadDocument({
        tenantId,
        title: title.trim() || file.name,
        tags,
        file,
      });
      setMessage(`Da enqueue ${response.root_job.job_type} cho ${response.document.title}.`);
      setTitle("");
      setTags("");
      setFile(null);
      await load();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Cannot upload document");
    } finally {
      setLoading(false);
    }
  };

  const ensureParsedPreview = async (documentId: string) => {
    setPreview((current) => {
      if (!current || current.document.id !== documentId || current.parsed || current.parsedLoading) {
        return current;
      }
      return { ...current, parsedLoading: true, parsedError: undefined };
    });
    try {
      const parsed = await fetchParsedPreview(documentId, tenantId);
      setPreview((current) =>
        current && current.document.id === documentId
          ? { ...current, parsed, parsedLoading: false, parsedError: undefined }
          : current,
      );
    } catch (error) {
      setPreview((current) =>
        current && current.document.id === documentId
          ? {
              ...current,
              parsedLoading: false,
              parsedError: error instanceof Error ? error.message : "Cannot load parsed preview",
            }
          : current,
      );
    }
  };

  const ensureChunkPreview = async (documentId: string) => {
    setPreview((current) => {
      if (!current || current.document.id !== documentId || current.chunks || current.chunksLoading) {
        return current;
      }
      return { ...current, chunksLoading: true, chunksError: undefined };
    });
    try {
      const chunks = await fetchChunkPreview(documentId, tenantId);
      setPreview((current) =>
        current && current.document.id === documentId
          ? { ...current, chunks, chunksLoading: false, chunksError: undefined }
          : current,
      );
    } catch (error) {
      setPreview((current) =>
        current && current.document.id === documentId
          ? {
              ...current,
              chunksLoading: false,
              chunksError: error instanceof Error ? error.message : "Cannot load chunk preview",
            }
          : current,
      );
    }
  };

  const openPreview = (document: DocumentRecord, activeTab: PreviewTab) => {
    setPreview({
      document,
      activeTab,
      parsedLoading: activeTab === "parsed",
      chunksLoading: activeTab === "chunks",
    });
    if (activeTab === "parsed") {
      void ensureParsedPreview(document.id);
    }
    if (activeTab === "chunks") {
      void ensureChunkPreview(document.id);
    }
  };

  const switchPreviewTab = (tab: PreviewTab) => {
    setPreview((current) => (current ? { ...current, activeTab: tab } : current));
    if (!preview) {
      return;
    }
    if (tab === "parsed" && !preview.parsed && !preview.parsedLoading) {
      void ensureParsedPreview(preview.document.id);
    }
    if (tab === "chunks" && !preview.chunks && !preview.chunksLoading) {
      void ensureChunkPreview(preview.document.id);
    }
  };

  return (
    <section className="grid min-h-0 min-w-0 gap-4 overflow-y-auto overflow-x-hidden pr-1 app-scrollbar">
      <div className="surface min-w-0 overflow-hidden rounded-lg">
        <div className="flex items-center justify-between gap-3 border-b border-slate-200 px-4 py-3">
          <div>
            <h2 className="text-sm font-bold">Kho tai lieu</h2>
            <div className="mt-1 text-xs text-slate-500">{readyCount}/{documents.length} document ready</div>
          </div>
          <button className="btn-secondary" disabled={loading} type="button" onClick={load}>
            <RefreshCw className={cx("h-4 w-4", loading && "animate-spin")} />
            Refresh
          </button>
        </div>

        <form className="grid gap-3 border-b border-slate-200 p-4" onSubmit={submit}>
          <div className="grid gap-3 md:grid-cols-2">
            <input className="field" value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Ten tai lieu" />
            <input className="field" value={tags} onChange={(event) => setTags(event.target.value)} placeholder="Tags, cach nhau boi dau phay" />
          </div>
          <div className="grid min-w-0 gap-3 md:grid-cols-[minmax(0,1fr)_auto]">
            <label
              className="flex min-w-0 cursor-pointer items-center gap-3 rounded-md border border-slate-200 bg-white px-3 py-2 text-sm text-ink-950 transition hover:border-slate-300"
              htmlFor={fileInputId}
            >
              <span className="shrink-0 font-semibold text-ink-950">Chon file</span>
              <span className="min-w-0 flex-1 truncate text-slate-500" title={file?.name ?? "Chua chon file nao"}>
                {file?.name ?? "Chua chon file nao"}
              </span>
            </label>
            <input
              className="sr-only"
              id={fileInputId}
              type="file"
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            />
            <button className="btn-primary" disabled={loading} type="submit">
              <UploadCloud className="h-4 w-4" />
              Upload
            </button>
          </div>
          {message ? <div className="rounded-md bg-slate-50 px-3 py-2 text-sm text-slate-600">{message}</div> : null}
        </form>

        <div className="max-h-[680px] divide-y divide-slate-100 overflow-y-auto overflow-x-hidden app-scrollbar">
          {documents.length === 0 ? (
            <div className="p-6 text-sm text-slate-500">Chua co tai lieu trong tenant nay.</div>
          ) : (
            documents.map((document) => (
              <article className="grid min-w-0 gap-3 p-4" key={document.id}>
                <div className="flex min-w-0 items-start justify-between gap-3">
                  <div className="flex min-w-0 flex-1 gap-3 overflow-hidden">
                    <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-slate-100 text-ocean-700">
                      <FileText className="h-5 w-5" />
                    </div>
                    <div className="min-w-0 flex-1 overflow-hidden">
                      <div className="truncate text-sm font-bold" title={document.title}>
                        {document.title}
                      </div>
                      <div
                        className="truncate text-xs text-slate-500"
                        title={`${document.file_name} | ${formatBytes(document.size_bytes)} | ${document.version}`}
                      >
                        {document.file_name} | {formatBytes(document.size_bytes)} | {document.version}
                      </div>
                    </div>
                  </div>
                  <StageBadge status={document.status} />
                </div>

                <ProgressBar document={document} />

                {document.current_job_error_message ? (
                  <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
                    {document.current_job_error_message}
                  </div>
                ) : null}

                <div className="flex flex-wrap items-center gap-2">
                  <button className="btn-secondary" type="button" onClick={() => openPreview(document, "raw")}>
                    <Eye className="h-4 w-4" />
                    Ban goc
                  </button>
                  <button className="btn-secondary" type="button" onClick={() => openPreview(document, "parsed")}>
                    <FileText className="h-4 w-4" />
                    OCR / parsed
                  </button>
                  <button className="btn-secondary" type="button" onClick={() => reprocessDocument(document.id, tenantId, "incremental").then(load).catch((error) => setMessage(error.message))}>
                    <RotateCw className="h-4 w-4" />
                    Reprocess
                  </button>
                  <button
                    className="btn-danger ml-auto"
                    type="button"
                    onClick={async () => {
                      if (!window.confirm(`Xoa document "${document.title}"?`)) {
                        return;
                      }
                      try {
                        await deleteDocument(document.id, tenantId);
                        await load();
                      } catch (error) {
                        setMessage(error instanceof Error ? error.message : "Cannot delete document");
                      }
                    }}
                  >
                    <Trash2 className="h-4 w-4" />
                    Xoa
                  </button>
                </div>
              </article>
            ))
          )}
        </div>
      </div>

      <div className="surface rounded-lg">
        <div className="border-b border-slate-200 px-4 py-3">
          <h3 className="text-sm font-bold">Recent jobs</h3>
        </div>
        <div className="max-h-64 divide-y divide-slate-100 overflow-auto app-scrollbar">
          {jobs.length === 0 ? (
            <div className="p-4 text-sm text-slate-500">Chua co job nao.</div>
          ) : (
            jobs.slice(0, 8).map((job) => (
              <div className="grid gap-2 p-4" key={job.id}>
                <div className="flex items-center justify-between gap-3">
                  <div className="truncate text-sm font-semibold">{job.stage_label ?? job.job_type}</div>
                  <StageBadge status={job.status} />
                </div>
                <div className="flex items-center justify-between gap-3 text-xs text-slate-500">
                  <span>{formatDateTime(job.created_at)}</span>
                  <span>{job.progress_percent}% {progressCounter(job.progress_current, job.progress_total) ?? ""}</span>
                </div>
              </div>
            ))
          )}
        </div>
      </div>

      {preview ? (
        <div className="fixed inset-0 z-50 grid bg-ink-950/40 p-4 backdrop-blur-sm lg:place-items-center" onClick={() => setPreview(null)}>
          <aside className="surface ml-auto grid h-full w-full max-w-5xl grid-rows-[auto_1fr] overflow-hidden rounded-lg" onClick={(event) => event.stopPropagation()}>
            <div className="flex items-center justify-between gap-3 border-b border-slate-200 px-4 py-3">
              <div className="min-w-0">
                <div className="truncate text-sm font-bold">{preview.document.title}</div>
                <div className="truncate text-xs text-slate-500">{preview.document.file_name}</div>
              </div>
              <div className="hidden items-center gap-2 md:flex">
                {(["raw", "parsed", "chunks"] as const).map((tab) => (
                  <button
                    key={tab}
                    className={cx(
                      "rounded-md px-3 py-2 text-xs font-semibold transition",
                      preview.activeTab === tab
                        ? "bg-ink-950 text-white"
                        : "bg-slate-100 text-slate-600 hover:bg-slate-200",
                    )}
                    type="button"
                    onClick={() => switchPreviewTab(tab)}
                  >
                    {tab === "raw" ? "Ban goc" : tab === "parsed" ? "OCR / parsed" : "Chunk"}
                  </button>
                ))}
              </div>
              <button className="icon-btn" type="button" onClick={() => setPreview(null)}>
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="min-h-0 overflow-auto bg-slate-50 p-4 app-scrollbar">
              <div className="mb-4 flex flex-wrap gap-2 md:hidden">
                {(["raw", "parsed", "chunks"] as const).map((tab) => (
                  <button
                    key={tab}
                    className={cx(
                      "rounded-md px-3 py-2 text-xs font-semibold transition",
                      preview.activeTab === tab
                        ? "bg-ink-950 text-white"
                        : "bg-white text-slate-600 ring-1 ring-slate-200 hover:bg-slate-100",
                    )}
                    type="button"
                    onClick={() => switchPreviewTab(tab)}
                  >
                    {tab === "raw" ? "Ban goc" : tab === "parsed" ? "OCR / parsed" : "Chunk"}
                  </button>
                ))}
              </div>
              {preview.activeTab === "raw" ? (
                <div className="grid gap-3">
                  <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs text-slate-500">
                    {previewTitle(preview.document)}
                  </div>
                  {renderRawPreview(preview.document, tenantId)}
                </div>
              ) : preview.activeTab === "parsed" && preview.parsedLoading ? (
                <div className="flex items-center gap-2 text-sm text-slate-600">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Dang tai parsed preview...
                </div>
              ) : preview.activeTab === "parsed" && preview.parsedError ? (
                <div className="rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-700">{preview.parsedError}</div>
              ) : preview.activeTab === "parsed" && preview.parsed ? (
                <div className="grid gap-4">
                  <div className="grid gap-3 md:grid-cols-3">
                    <div className="rounded-lg border border-slate-200 bg-white p-3">
                      <div className="label">Language</div>
                      <div className="mt-1 font-semibold">{preview.parsed.language}</div>
                    </div>
                    <div className="rounded-lg border border-slate-200 bg-white p-3">
                      <div className="label">OCR</div>
                      <div className="mt-1 font-semibold">{preview.parsed.ocr_applied ? "applied" : "not applied"}</div>
                    </div>
                    <div className="rounded-lg border border-slate-200 bg-white p-3">
                      <div className="label">Quality</div>
                      <div className="mt-1 font-semibold">{preview.parsed.parse_quality_score.toFixed(2)}</div>
                    </div>
                  </div>
                  <pre className="whitespace-pre-wrap rounded-lg border border-slate-200 bg-white p-4 font-mono text-sm leading-7 text-slate-800">
                    {preview.parsed.plain_text || "Khong co plain text."}
                  </pre>
                </div>
              ) : preview.activeTab === "chunks" && preview.chunksLoading ? (
                <div className="flex items-center gap-2 text-sm text-slate-600">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Dang tai chunk preview...
                </div>
              ) : preview.activeTab === "chunks" && preview.chunksError ? (
                <div className="rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-700">{preview.chunksError}</div>
              ) : preview.activeTab === "chunks" && preview.chunks ? (
                <div className="grid gap-4">
                  <div className="grid gap-3 md:grid-cols-3">
                    <div className="rounded-lg border border-slate-200 bg-white p-3">
                      <div className="label">Tong chunk</div>
                      <div className="mt-1 font-semibold">{preview.chunks.total_chunks}</div>
                    </div>
                    <div className="rounded-lg border border-slate-200 bg-white p-3">
                      <div className="label">Target tokens</div>
                      <div className="mt-1 font-semibold">{preview.chunks.chunk_target_tokens}</div>
                    </div>
                    <div className="rounded-lg border border-slate-200 bg-white p-3">
                      <div className="label">Overlap</div>
                      <div className="mt-1 font-semibold">{preview.chunks.chunk_overlap_tokens}</div>
                    </div>
                  </div>
                  <div className="grid gap-3">
                    {preview.chunks.items.map((chunk) => (
                      <article className="rounded-lg border border-slate-200 bg-white p-4" key={chunk.chunk_id}>
                        <div className="flex flex-wrap items-start justify-between gap-3">
                          <div className="min-w-0">
                            <div className="text-sm font-bold text-slate-800">
                              Chunk #{chunk.chunk_index + 1} <span className="font-normal text-slate-500">({chunk.token_estimate} tokens)</span>
                            </div>
                            <div className="mt-1 text-xs text-slate-500">
                              {(chunk.heading_path.length > 0 ? chunk.heading_path.join(" > ") : chunk.section_name) || "body"}
                            </div>
                          </div>
                          <div className="text-right text-xs text-slate-500">
                            <div>{chunk.page_start ? `Trang ${chunk.page_start}${chunk.page_end && chunk.page_end !== chunk.page_start ? `-${chunk.page_end}` : ""}` : "Khong ro trang"}</div>
                            <div>{chunk.parse_quality_score != null ? `Quality ${chunk.parse_quality_score.toFixed(2)}` : "No quality score"}</div>
                          </div>
                        </div>
                        <pre className="mt-3 whitespace-pre-wrap break-words rounded-md bg-slate-50 p-3 font-mono text-xs leading-6 text-slate-700">
                          {chunk.content}
                        </pre>
                      </article>
                    ))}
                  </div>
                </div>
              ) : null}
            </div>
          </aside>
        </div>
      ) : null}
    </section>
  );
}
