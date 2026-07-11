"use client";

import { useEffect, useState, useTransition } from "react";

import {
  deleteDocument,
  fetchDocuments,
  fetchParsedPreview,
  rawDocumentPreviewUrl,
  type DocumentRecord,
  type ParsedPreview,
  uploadDocument,
} from "../lib/api";

function formatBytes(value?: number | null) {
  if (!value) {
    return "n/a";
  }
  if (value < 1024) {
    return `${value} B`;
  }
  if (value < 1024 * 1024) {
    return `${(value / 1024).toFixed(1)} KB`;
  }
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function statusClassName(status?: string | null) {
  if (status === "processed" || status === "completed") {
    return "status-ok";
  }
  if (status === "queued" || status === "processing" || status === "running") {
    return "status-live";
  }
  return "status-warn";
}

const stageLabels: Record<string, string> = {
  "document.parse": "Parse canonical",
  "document.chunk": "Chunk + provenance",
  "document.embed": "Embedding",
  "graph.extract": "Entity extraction",
  "graph.upsert": "Neo4j upsert",
};

function progressLabel(document: DocumentRecord) {
  if (document.processing_progress_label) {
    return document.processing_progress_label;
  }
  if (document.current_job_type && document.current_job_status) {
    return `${stageLabels[document.current_job_type] ?? document.current_job_type} | ${document.current_job_status}`;
  }
  return document.status;
}

function progressDetail(document: DocumentRecord) {
  if (document.current_job_error_message && document.status === "failed") {
    return document.current_job_error_message;
  }
  return document.processing_progress_detail ?? null;
}

function hasActiveProcessing(documents: DocumentRecord[]) {
  return documents.some(
    (document) =>
      document.status === "queued" ||
      document.status === "processing" ||
      document.current_job_status === "queued" ||
      document.current_job_status === "running",
  );
}

type PreviewMode = "raw" | "parsed";

export function DocumentPanel({ tenantId }: { tenantId: string }) {
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [title, setTitle] = useState("Quy trinh cap phat PPE");
  const [tags, setTags] = useState("an-toan, ppe");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [preview, setPreview] = useState<ParsedPreview | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [previewDocument, setPreviewDocument] = useState<DocumentRecord | null>(null);
  const [previewMode, setPreviewMode] = useState<PreviewMode>("raw");
  const [isPending, startTransition] = useTransition();
  const [isPreviewPending, startPreviewTransition] = useTransition();

  const reloadDocuments = () => {
    startTransition(() => {
      void (async () => {
        const items = await fetchDocuments(tenantId);
        setDocuments(items);
      })();
    });
  };

  const openPreview = (document: DocumentRecord, mode: PreviewMode) => {
    setPreviewDocument(document);
    setPreviewMode(mode);
    setPreviewError(null);
    if (mode === "raw") {
      setPreview(null);
      return;
    }

    startPreviewTransition(() => {
      void (async () => {
        try {
          const next = await fetchParsedPreview(document.id, tenantId);
          setPreview(next);
        } catch (error) {
          setPreview(null);
          setPreviewError(error instanceof Error ? error.message : "Khong tai duoc parsed preview");
        }
      })();
    });
  };

  useEffect(() => {
    reloadDocuments();
    setPreview(null);
    setPreviewError(null);
    setPreviewDocument(null);
  }, [tenantId]);

  useEffect(() => {
    if (!tenantId || !hasActiveProcessing(documents)) {
      return;
    }

    const timer = window.setInterval(() => {
      reloadDocuments();
    }, 5000);

    return () => window.clearInterval(timer);
  }, [documents, tenantId]);

  return (
    <>
      <section className="panel">
        <div className="panel-header">
          <div>
            <h2>Quan Ly Tai Lieu</h2>
            <p className="muted">
              Upload tai lieu cua tenant, theo doi tien trinh RAG, va mo file goc hoac ban parsed/OCR.
              Khi xoa document, he thong se don ca raw file, OCR artifacts, chunks, embeddings, jobs, va graph data lien quan.
            </p>
          </div>
          <div className="button-row compact-row">
            <div className="pill">{documents.length} documents</div>
            <button className="button ghost" type="button" onClick={reloadDocuments}>
              {isPending ? "Dang dong bo..." : "Lam moi"}
            </button>
          </div>
        </div>

        <div className="input-grid two-columns">
          <input
            className="input"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="Ten tai lieu"
          />
          <input
            className="input"
            value={tags}
            onChange={(event) => setTags(event.target.value)}
            placeholder="Tags, phan cach boi dau phay"
          />
          <div className="tenant-badge-box">
            <span className="meta-label">tenant scope</span>
            <strong>{tenantId}</strong>
          </div>
          <input
            className="input"
            type="file"
            onChange={(event) => setSelectedFile(event.target.files?.[0] ?? null)}
          />
        </div>

        <div className="button-row">
          <button
            className="button"
            disabled={isPending}
            type="button"
            onClick={() => {
              startTransition(() => {
                void (async () => {
                  if (!selectedFile) {
                    setMessage("Can chon file truoc khi upload.");
                    return;
                  }
                  const response = await uploadDocument({
                    tenantId,
                    title,
                    tags,
                    file: selectedFile,
                  });
                  const items = await fetchDocuments(tenantId);
                  setDocuments(items);
                  setMessage(
                    `Da tao document ${response.document.title} va enqueue job ${response.root_job.job_type} (${response.root_job.status}).`,
                  );
                })();
              });
            }}
          >
            {isPending ? "Dang upload..." : "Upload vao ingest"}
          </button>
        </div>

        {message ? <p className="muted">{message}</p> : null}

        <div className="list-box">
          {documents.length === 0 ? (
            <div className="muted">Chua co tai lieu nao trong he thong.</div>
          ) : (
            documents.map((document) => (
              <article className="document-card" key={document.id}>
                <div className="document-card-top">
                  <div>
                    <strong>{document.title}</strong>
                    <div className="muted">
                      {document.file_name} | {document.content_type} | {formatBytes(document.size_bytes)}
                    </div>
                  </div>
                  <div className={statusClassName(document.status)}>{document.status}</div>
                </div>

                <div className="document-meta-grid">
                  <div>
                    <span className="meta-label">tenant</span>
                    <div>{document.tenant_id}</div>
                  </div>
                  <div>
                    <span className="meta-label">version</span>
                    <div>{document.version}</div>
                  </div>
                  <div>
                    <span className="meta-label">rag progress</span>
                    <div>{progressLabel(document)}</div>
                  </div>
                  <div>
                    <span className="meta-label">job status</span>
                    <div>{document.processing_stage_status ?? document.current_job_status ?? "n/a"}</div>
                  </div>
                </div>

                <div className="document-progress-stack">
                  <div className="document-progress-head">
                    <span className="meta-label">
                      {document.processing_stage_label ?? "Pipeline"}
                      {document.processing_mode ? ` | ${document.processing_mode}` : ""}
                    </span>
                    <strong>{document.processing_progress_percent}%</strong>
                  </div>
                  <div className="progress-track" aria-hidden="true">
                    <div
                      className={`progress-fill ${statusClassName(document.processing_stage_status ?? document.status)}`}
                      style={{ width: `${document.processing_progress_percent}%` }}
                    />
                  </div>
                  {progressDetail(document) ? (
                    <div className="muted tiny">{progressDetail(document)}</div>
                  ) : null}
                </div>

                {document.current_job_error_message && document.status === "failed" ? (
                  <div className="status-warn">{document.current_job_error_message}</div>
                ) : null}

                <div className="button-row">
                  <button
                    className="button ghost"
                    type="button"
                    onClick={() => openPreview(document, "raw")}
                  >
                    Xem tai lieu goc
                  </button>
                  <button
                    className="button ghost"
                    type="button"
                    onClick={() => openPreview(document, "parsed")}
                  >
                    Xem sau OCR
                  </button>
                  <button
                    className="button ghost"
                    type="button"
                    onClick={() => {
                      const confirmed = window.confirm(
                        `Xoa document ${document.title}? Hanh dong nay se xoa raw file, OCR artifacts, chunks, embeddings, jobs, va graph data lien quan.`,
                      );
                      if (!confirmed) {
                        return;
                      }
                      startTransition(() => {
                        void (async () => {
                          const result = await deleteDocument(document.id, tenantId);
                          const items = await fetchDocuments(tenantId);
                          setDocuments(items);
                          setMessage(`Da xoa document ${result.title} va toan bo du lieu lien quan.`);
                          if (previewDocument?.id === document.id) {
                            setPreviewDocument(null);
                            setPreview(null);
                            setPreviewError(null);
                          }
                        })();
                      });
                    }}
                  >
                    Xoa document
                  </button>
                </div>
              </article>
            ))
          )}
        </div>
      </section>

      {previewDocument ? (
        <div className="preview-drawer-backdrop" onClick={() => setPreviewDocument(null)}>
          <aside
            className="preview-drawer"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="preview-drawer-header">
              <div>
                <div className="eyebrow">Document Preview</div>
                <strong>{previewDocument.title}</strong>
                <div className="muted">{previewDocument.file_name}</div>
              </div>
              <button className="button ghost" type="button" onClick={() => setPreviewDocument(null)}>
                Dong
              </button>
            </div>

            <div className="preview-toolbar">
              <button
                className={`preview-tab ${previewMode === "raw" ? "is-active" : ""}`}
                type="button"
                onClick={() => openPreview(previewDocument, "raw")}
              >
                Ban goc
              </button>
              <button
                className={`preview-tab ${previewMode === "parsed" ? "is-active" : ""}`}
                type="button"
                onClick={() => openPreview(previewDocument, "parsed")}
              >
                Parsed / OCR
              </button>
              <a
                className="button ghost"
                href={rawDocumentPreviewUrl(previewDocument.id, tenantId)}
                rel="noreferrer"
                target="_blank"
              >
                Mo tab moi
              </a>
            </div>

            <div className="preview-body">
              {previewMode === "raw" ? (
                <iframe
                  className="preview-frame"
                  src={rawDocumentPreviewUrl(previewDocument.id, tenantId)}
                  title={`raw-preview-${previewDocument.id}`}
                />
              ) : isPreviewPending ? (
                <div className="muted">Dang tai parsed/OCR preview...</div>
              ) : previewError ? (
                <div className="status-warn">{previewError}</div>
              ) : preview ? (
                <div className="preview-stack">
                  <div className="detail-grid">
                    <div className="detail-card">
                      <span className="meta-label">language</span>
                      <strong>{preview.language}</strong>
                    </div>
                    <div className="detail-card">
                      <span className="meta-label">ocr applied</span>
                      <strong>{preview.ocr_applied ? "yes" : "no"}</strong>
                    </div>
                    <div className="detail-card">
                      <span className="meta-label">parse quality</span>
                      <strong>{preview.parse_quality_score.toFixed(2)}</strong>
                    </div>
                  </div>

                  {preview.parse_warnings.length > 0 ? (
                    <div className="callout">
                      <strong>Parse warnings</strong>
                      <ul className="flat-list">
                        {preview.parse_warnings.map((item) => (
                          <li key={item}>{item}</li>
                        ))}
                      </ul>
                    </div>
                  ) : null}

                  <pre className="preview-text">{preview.plain_text || "Khong co plain text."}</pre>
                </div>
              ) : (
                <div className="muted">Chua co parsed preview.</div>
              )}
            </div>
          </aside>
        </div>
      ) : null}
    </>
  );
}
