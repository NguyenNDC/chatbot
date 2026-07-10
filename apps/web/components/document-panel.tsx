"use client";

import { useEffect, useState, useTransition } from "react";

import { fetchDocuments, type DocumentRecord, uploadDocument } from "../lib/api";

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
  return status === "processed" || status === "completed" ? "status-ok" : "status-warn";
}

export function DocumentPanel() {
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [tenantId, setTenantId] = useState("tenant-demo");
  const [title, setTitle] = useState("Quy trinh cap phat PPE");
  const [tags, setTags] = useState("an-toan, ppe");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  const reloadDocuments = () => {
    startTransition(() => {
      void (async () => {
        const items = await fetchDocuments();
        setDocuments(items);
      })();
    });
  };

  useEffect(() => {
    reloadDocuments();
  }, []);

  return (
    <section className="panel">
      <div className="panel-header">
        <div>
          <h2>Kho Tai Lieu</h2>
          <p className="muted">
            Upload tai lieu nguon vao ingest pipeline va theo doi document/version dang duoc xu ly.
          </p>
        </div>
        <div className="button-row compact-row">
          <div className="pill">{documents.length} documents</div>
          <button className="button ghost" type="button" onClick={reloadDocuments}>
            Lam moi
          </button>
        </div>
      </div>

      <div className="input-grid two-columns">
        <input
          className="input"
          value={tenantId}
          onChange={(event) => setTenantId(event.target.value)}
          placeholder="Tenant ID"
        />
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
                const items = await fetchDocuments();
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
                  <span className="meta-label">job</span>
                  <div>{document.current_job_type ?? "none"}</div>
                </div>
                <div>
                  <span className="meta-label">job status</span>
                  <div>{document.current_job_status ?? "n/a"}</div>
                </div>
              </div>
            </article>
          ))
        )}
      </div>
    </section>
  );
}
