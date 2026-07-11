import { FormEvent, useEffect, useMemo, useState } from "react";
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
  fetchParsedPreview,
  rawDocumentPreviewUrl,
  reprocessDocument,
  uploadDocument,
  type DocumentRecord,
  type JobRecord,
  type ParsedPreview,
} from "../lib/api";
import { cx, formatBytes, formatDateTime, progressCounter, statusTone } from "../lib/format";

type PreviewState =
  | { mode: "raw"; document: DocumentRecord }
  | { mode: "parsed"; document: DocumentRecord; parsed?: ParsedPreview; loading?: boolean; error?: string };

function StageBadge({ status }: { status?: string | null }) {
  const tone = statusTone(status);
  return (
    <span
      className={cx(
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

  const openParsedPreview = async (document: DocumentRecord) => {
    setPreview({ mode: "parsed", document, loading: true });
    try {
      const parsed = await fetchParsedPreview(document.id, tenantId);
      setPreview({ mode: "parsed", document, parsed });
    } catch (error) {
      setPreview({
        mode: "parsed",
        document,
        error: error instanceof Error ? error.message : "Cannot load parsed preview",
      });
    }
  };

  return (
    <section className="grid min-w-0 gap-4">
      <div className="surface rounded-lg">
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
          <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_auto]">
            <input className="field py-2" type="file" onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
            <button className="btn-primary" disabled={loading} type="submit">
              <UploadCloud className="h-4 w-4" />
              Upload
            </button>
          </div>
          {message ? <div className="rounded-md bg-slate-50 px-3 py-2 text-sm text-slate-600">{message}</div> : null}
        </form>

        <div className="max-h-[680px] divide-y divide-slate-100 overflow-auto app-scrollbar">
          {documents.length === 0 ? (
            <div className="p-6 text-sm text-slate-500">Chua co tai lieu trong tenant nay.</div>
          ) : (
            documents.map((document) => (
              <article className="grid gap-3 p-4" key={document.id}>
                <div className="flex items-start justify-between gap-3">
                  <div className="flex min-w-0 gap-3">
                    <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-slate-100 text-ocean-700">
                      <FileText className="h-5 w-5" />
                    </div>
                    <div className="min-w-0">
                      <div className="truncate text-sm font-bold">{document.title}</div>
                      <div className="truncate text-xs text-slate-500">
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
                  <button className="btn-secondary" type="button" onClick={() => setPreview({ mode: "raw", document })}>
                    <Eye className="h-4 w-4" />
                    Ban goc
                  </button>
                  <button className="btn-secondary" type="button" onClick={() => openParsedPreview(document)}>
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
              <button className="icon-btn" type="button" onClick={() => setPreview(null)}>
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="min-h-0 overflow-auto bg-slate-50 p-4 app-scrollbar">
              {preview.mode === "raw" ? (
                <iframe className="h-full min-h-[78vh] w-full rounded-md border border-slate-200 bg-white" src={rawDocumentPreviewUrl(preview.document.id, tenantId)} title={preview.document.title} />
              ) : preview.loading ? (
                <div className="flex items-center gap-2 text-sm text-slate-600">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Dang tai parsed preview...
                </div>
              ) : preview.error ? (
                <div className="rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-700">{preview.error}</div>
              ) : preview.parsed ? (
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
              ) : null}
            </div>
          </aside>
        </div>
      ) : null}
    </section>
  );
}
